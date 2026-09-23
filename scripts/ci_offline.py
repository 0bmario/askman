#!/usr/bin/env python3
"""Provision pinned CI assets, then verify the bundle and query path offline."""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import io
import json
import os
import platform
import queue
import re
import signal
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import tomllib
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "Qdrant/all-MiniLM-L6-v2-onnx"
MODEL_CACHE_FOLDER = "models--Qdrant--all-MiniLM-L6-v2-onnx"
MODEL_REVISION = "5f1b8cd78bc4fb444dd171e59b18f3a3af89a079"
COMMAND_TIMEOUT_SECONDS = 300
MODEL_FILES = {
    "config.json": "1b4d8e2a3988377ed8b519a31d8d31025a25f1c5f8606998e8014111438efcd7",
    "model.onnx": "bbd7b466f6d58e646fdc2bd5fd67b2f5e93c0b687011bd4548c420f7bd46f0c5",
    "special_tokens_map.json": "5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a",
    "tokenizer.json": "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0",
    "tokenizer_config.json": "bd2e06a5b20fd1b13ca988bedc8763d332d242381b4fbc98f8fead4524158f79",
}
BENCHMARK_INPUTS = (
    "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json",
    "tests/fixtures/tldr-evaluation-v2/manifest.json",
    "tests/fixtures/evaluation/frozen-dev-v2-expanded.json",
    "tests/fixtures/evaluation/frozen-holdout-v2-expanded.json",
    "tests/fixtures/evaluation/task-intents-v2-expanded.json",
    "tests/fixtures/evaluation/evaluation-v2-support-catalog-expanded.json",
    "tests/fixtures/evaluation/evaluation-v2-corpus-catalog-expanded.json",
    "scripts/evaluate_retrieval.py",
    "scripts/validate_evaluation_v2.py",
)
TARGET_QUERIES = (
    ("common", (), "copy files", "common", "pages/common/cp.md"),
    ("linux", ("--linux",), "search patterns files", "linux", "pages/linux/grep.md"),
    ("osx", ("--osx",), "copy text to clipboard", "osx", "pages/osx/pbcopy.md"),
    ("windows", ("--windows",), "print formatted value", "windows", "pages/windows/printf.md"),
)


class VerificationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def download_verified(url: str, destination: Path, expected_sha256: str) -> None:
    if destination.exists():
        actual = sha256_file(destination)
        if actual == expected_sha256:
            return
        raise VerificationError(
            f"existing asset has wrong SHA256: {destination} "
            f"expected={expected_sha256} actual={actual}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    try:
        request = Request(url, headers={"User-Agent": "askman-ci-verifier"})
        with urlopen(request, timeout=120) as response, temporary.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        actual = sha256_file(temporary)
        if actual != expected_sha256:
            raise VerificationError(
                f"downloaded asset has wrong SHA256: {url} "
                f"expected={expected_sha256} actual={actual}"
            )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def model_cache_path(work_dir: Path) -> Path:
    return work_dir / "model-cache"


def package_version() -> str:
    with (ROOT / "Cargo.toml").open("rb") as stream:
        return tomllib.load(stream)["package"]["version"]


def provision(work_dir: Path, report_dir: Path) -> None:
    cache = model_cache_path(work_dir)
    model_root = cache / MODEL_CACHE_FOLDER
    snapshot = model_root / "snapshots" / MODEL_REVISION
    base_url = f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}"

    for filename, expected_sha256 in MODEL_FILES.items():
        download_verified(base_url + "/" + filename, snapshot / filename, expected_sha256)

    reference = model_root / "refs" / "main"
    reference.parent.mkdir(parents=True, exist_ok=True)
    if reference.exists() and reference.read_bytes() != MODEL_REVISION.encode("ascii"):
        raise VerificationError(f"model cache reference is not pinned: {reference}")
    with reference.open("wb") as stream:
        stream.write(MODEL_REVISION.encode("ascii"))
        stream.flush()
        os.fsync(stream.fileno())

    write_json(
        report_dir / "provisioned-assets.json",
        {
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "model_cache": str(cache),
            "assets": {
                filename: {
                    "path": str(snapshot / filename),
                    "sha256": expected_sha256,
                    "size_bytes": (snapshot / filename).stat().st_size,
                }
                for filename, expected_sha256 in MODEL_FILES.items()
            },
        },
    )
    print(f"Provisioned pinned model assets in {cache}")


def run_logged(
    label: str,
    command: list[object],
    report_dir: Path,
    *,
    environment: dict[str, str] | None = None,
    expect_failure: bool = False,
    allow_published_bundle_after_abort: bool = False,
) -> str:
    started_at = time.monotonic()
    log_path = report_dir / "logs" / f"{label}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = " ".join(shlex.quote(str(argument)) for argument in command)
    print(f"$ {rendered}", flush=True)
    process_environment = os.environ.copy()
    if environment:
        process_environment.update(environment)

    process_options: dict[str, object] = {}
    if os.name == "nt":
        process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        process_options["start_new_session"] = True

    process = subprocess.Popen(
        [str(argument) for argument in command],
        cwd=ROOT,
        env=process_environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **process_options,
    )
    output_queue: queue.Queue[str | None] = queue.Queue()

    def drain_output() -> None:
        assert process.stdout is not None
        try:
            while chunk := process.stdout.read(4096):
                output_queue.put(chunk)
        finally:
            output_queue.put(None)

    reader = threading.Thread(target=drain_output, daemon=True)
    reader.start()
    output_parts: list[str] = []
    timed_out = False
    deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
    log_stream = log_path.open("w", encoding="utf-8")
    log_stream.write(f"$ {rendered}\n\n")
    log_stream.flush()

    def record_output(chunk: str) -> None:
        output_parts.append(chunk)
        log_stream.write(chunk)
        log_stream.flush()
        print(chunk, end="", flush=True)

    while process.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            chunk = output_queue.get(timeout=min(1.0, remaining))
        except queue.Empty:
            continue
        if chunk is None:
            break
        record_output(chunk)

    if timed_out:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    elif process.returncode is None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=5)

    reader.join(timeout=5)
    while True:
        try:
            chunk = output_queue.get_nowait()
        except queue.Empty:
            break
        if chunk is None:
            continue
        record_output(chunk)
    if process.stdout is not None:
        process.stdout.close()
    log_stream.close()

    if timed_out:
        raise VerificationError(
            f"{label} timed out after {COMMAND_TIMEOUT_SECONDS} seconds; see {log_path}"
        )

    return_code = process.returncode
    if expect_failure and return_code == 0:
        raise VerificationError(f"{label} unexpectedly succeeded; see {log_path}")
    published_bundle_after_abort = (
        allow_published_bundle_after_abort
        and return_code != 0
        and "built matching bundle" in "".join(output_parts)
    )
    if not expect_failure and return_code != 0 and not published_bundle_after_abort:
        raise VerificationError(
            f"{label} failed with exit status {return_code}; see {log_path}"
        )
    if published_bundle_after_abort:
        print(
            f"[ci-offline] {label} published its bundle before process teardown "
            f"(exit status {return_code}); validating the published output",
            flush=True,
        )
    print(f"[ci-offline] {label} completed in {time.monotonic() - started_at:.1f}s", flush=True)
    return "".join(output_parts)


def command_version(command: str) -> str:
    completed = subprocess.run(
        [command, "--version"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return (completed.stdout or "").strip()


def git_revision() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        return "unavailable"
    return (completed.stdout or "").strip()


def validate_provisioned_assets(work_dir: Path, report_dir: Path) -> None:
    metadata_path = report_dir / "provisioned-assets.json"
    if not metadata_path.is_file():
        raise VerificationError(f"missing provisioning record: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata["model_revision"] != MODEL_REVISION:
        raise VerificationError("provisioned model revision does not match the pin")
    for filename, expected_sha256 in MODEL_FILES.items():
        path = model_cache_path(work_dir) / MODEL_CACHE_FOLDER / "snapshots" / MODEL_REVISION / filename
        if not path.is_file() or sha256_file(path) != expected_sha256:
            raise VerificationError(f"provisioned model asset failed verification: {path}")
    reference = model_cache_path(work_dir) / MODEL_CACHE_FOLDER / "refs" / "main"
    if reference.read_bytes() != MODEL_REVISION.encode("ascii"):
        raise VerificationError(f"provisioned model reference failed verification: {reference}")


def benchmark_digests() -> dict[str, object]:
    result: dict[str, object] = {}
    for relative in BENCHMARK_INPUTS:
        path = ROOT / relative
        result[relative] = {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return result


def target_binary(name: str, profile: str = "debug") -> Path:
    binary = ROOT / "target" / profile / name
    if os.name == "nt":
        binary = binary.with_suffix(".exe")
    return binary


def _runtime_search_roots() -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    for variable in ("ORT_LIBRARY_PATH", "ORT_LIB_LOCATION", "ORT_ROOT"):
        value = os.environ.get(variable)
        if value:
            roots.append((f"env:{variable}", Path(value)))

    # An explicit provisioned root is authoritative. Do not even enumerate
    # ort-sys/pyke cache locations in that mode; this keeps runtime evidence
    # auditable and prevents a cache from becoming a silent fallback.
    if not roots:
        home = Path.home()
        roots.extend(
            [
                ("cache:ort.pyke.io", home / ".cache" / "ort.pyke.io"),
                ("cache:ort", home / ".cache" / "ort"),
            ]
        )
        if xdg_cache_home := os.environ.get("XDG_CACHE_HOME"):
            roots.append(("cache:XDG_CACHE_HOME", Path(xdg_cache_home) / "ort.pyke.io"))
        if platform.system() == "Darwin":
            roots.append(("cache:Library/Caches", home / "Library" / "Caches" / "ort.pyke.io"))
        if local_app_data := os.environ.get("LOCALAPPDATA"):
            roots.append(("cache:LOCALAPPDATA", Path(local_app_data) / "ort.pyke.io"))
        if program_data := os.environ.get("PROGRAMDATA"):
            roots.append(("cache:PROGRAMDATA", Path(program_data) / "onnxruntime"))

    unique: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for source, root in roots:
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            continue
        if resolved not in seen and resolved.exists():
            seen.add(resolved)
            unique.append((source, resolved))
    return unique


def _runtime_library_candidates(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []

    patterns = {
        "Darwin": ("libonnxruntime*.dylib",),
        "Linux": ("libonnxruntime*.so*",),
        "Windows": ("onnxruntime*.dll",),
    }.get(platform.system(), ("*onnxruntime*",))
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(path for path in root.rglob(pattern) if path.is_file())
    return sorted(set(candidates), key=lambda path: (len(path.parts), str(path)))


def _runtime_linkage(binary: Path, library: Path | None) -> dict[str, object]:
    if platform.system() == "Darwin":
        tool = shutil.which("otool")
        command = [tool, "-L", str(binary)] if tool else []
    elif platform.system() == "Linux":
        tool = shutil.which("ldd")
        command = [tool, str(binary)] if tool else []
    elif platform.system() == "Windows":
        tool = shutil.which("dumpbin") or shutil.which("objdump")
        command = (
            [tool, "/DEPENDENTS", str(binary)]
            if tool and "dumpbin" in Path(tool).name.lower()
            else ([tool, "-p", str(binary)] if tool else [])
        )
    else:
        tool = None
        command = []

    if not command:
        return {
            "tool": None,
            "command": None,
            "output": "",
            "contains_library": False,
            "expected_library_path": str(library) if library else None,
            "linkage_verified": False,
        }

    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = completed.stdout or ""
    library_names = {library.name, library.as_posix()} if library else set()
    contains_library = any(name and name in output for name in library_names)
    if not contains_library and library is not None and platform.system() == "Linux":
        canonical_library = library.resolve()
        for match in re.finditer(r"=>\s+([^\s()]+)", output):
            dependency = Path(match.group(1).rstrip(","))
            if not dependency.is_absolute() or "onnxruntime" not in dependency.name.lower():
                continue
            try:
                if dependency.resolve() == canonical_library:
                    contains_library = True
                    break
            except OSError:
                continue
    unresolved = bool(re.search(r"=>\s+not found\b", output, re.IGNORECASE))
    return {
        "tool": tool,
        "command": [str(part) for part in command],
        "output": output[-12000:],
        "contains_library": contains_library,
        "expected_library_path": str(library) if library else None,
        "resolved": not unresolved,
        "linkage_verified": contains_library and not unresolved,
        "exit_code": completed.returncode,
    }


def _runtime_version(path: Path | None) -> str | None:
    if path is None:
        return os.environ.get("ORT_VERSION") or os.environ.get("ORT_EXPECTED_VERSION")
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", str(path))
    return match.group(1) if match else (
        os.environ.get("ORT_VERSION") or os.environ.get("ORT_EXPECTED_VERSION")
    )


def _linked_runtime_path(binary: Path | None) -> Path | None:
    """Resolve an absolute native runtime path from the binary's dependency list."""

    if binary is None or not binary.is_file():
        return None
    linkage = _runtime_linkage(binary, None)
    output = str(linkage.get("output", ""))
    if re.search(r"=>\s+not found\b", output, re.IGNORECASE):
        return None
    candidates: list[Path] = []
    for match in re.finditer(r"(?:=>\s+|\s)([^\s()]*onnxruntime[^\s()]*)", output, re.IGNORECASE):
        token = match.group(1).rstrip(",")
        candidate = Path(token)
        if candidate.is_file():
            return candidate.resolve()
        candidates.append(Path(token).name)
    # macOS commonly reports @rpath/libonnxruntime... rather than the resolved
    # cache path. Resolve that basename only inside the pinned search roots.
    for name in candidates:
        for _, root in _runtime_search_roots():
            for candidate in _runtime_library_candidates(root):
                if candidate.name == name:
                    return candidate.resolve()
    return None


def runtime_metadata(binary_paths: dict[str, Path | None] | None = None) -> dict[str, object]:
    """Capture reproducible native-runtime and binary identity for CI artifacts."""

    searched_roots = [
        {"source": source, "path": str(path)}
        for source, path in _runtime_search_roots()
    ]
    library: Path | None = None
    resolution = "not-found"
    primary_binary = next(
        (binary for binary in (binary_paths or {}).values() if binary and binary.is_file()),
        None,
    )
    linked_runtime = _linked_runtime_path(primary_binary)
    if linked_runtime:
        library = linked_runtime
        resolution = "binary-linkage"
    else:
        for source, root in _runtime_search_roots():
            candidates = _runtime_library_candidates(root)
            if candidates:
                library = candidates[0]
                resolution = source
                break

    runtime: dict[str, object] = {
        "os": platform.system().lower(),
        "machine": platform.machine(),
        "resolution": resolution,
        "linked_runtime_path": str(linked_runtime) if linked_runtime else None,
        "searched_roots": searched_roots,
        "library_path": str(library) if library else None,
        "library_sha256": sha256_file(library) if library else None,
        "version": _runtime_version(library),
        "library_name": library.name if library else None,
        "environment": {
            key: os.environ[key]
            for key in ("ORT_VERSION", "ORT_LIB_LOCATION", "ORT_LIBRARY_PATH", "ORT_ROOT")
            if key in os.environ
        },
    }

    binaries: dict[str, object] = {}
    for label, binary in (binary_paths or {}).items():
        record: dict[str, object] = {"path": str(binary) if binary else None}
        if binary and binary.is_file():
            record["sha256"] = sha256_file(binary)
            record["size_bytes"] = binary.stat().st_size
            record["linkage"] = _runtime_linkage(binary, library)
        else:
            record["sha256"] = None
            record["size_bytes"] = None
            record["linkage"] = None
        binaries[label] = record
    runtime["linkage"] = {
        label: record.get("linkage")
        for label, record in binaries.items()
        if isinstance(record, dict)
    }
    shipping_record = binaries.get("shipping")
    if isinstance(shipping_record, dict):
        runtime["binary_path"] = shipping_record.get("path")
        runtime["binary_sha256"] = shipping_record.get("sha256")
    return {"onnx_runtime": runtime, "binaries": binaries}


def require_runtime_identity(
    evidence: dict[str, object],
    *,
    expected_version: str | None = None,
    binary_label: str = "shipping",
) -> None:
    """Fail closed unless the exact linked runtime and binary are identifiable."""

    runtime = evidence.get("onnx_runtime")
    binaries = evidence.get("binaries")
    if not isinstance(runtime, dict) or not isinstance(binaries, dict):
        raise VerificationError("runtime evidence is missing native identity records")
    version = runtime.get("version")
    library_path = runtime.get("library_path")
    library_sha = runtime.get("library_sha256")
    resolution = runtime.get("resolution")
    if not isinstance(version, str) or not version:
        raise VerificationError("linked ONNX Runtime version is missing")
    if expected_version and version != expected_version:
        raise VerificationError(
            f"linked ONNX Runtime version is {version!r}, expected {expected_version!r}"
        )
    if not isinstance(library_path, str) or not Path(library_path).is_file():
        raise VerificationError("linked ONNX Runtime library path is missing or not a file")
    if not isinstance(library_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", library_sha):
        raise VerificationError("linked ONNX Runtime library SHA256 is missing")
    if sha256_file(Path(library_path)) != library_sha:
        raise VerificationError("linked ONNX Runtime library changed after identity capture")
    record = binaries.get(binary_label)
    if not isinstance(record, dict):
        raise VerificationError(f"runtime evidence is missing {binary_label} binary identity")
    binary_path = record.get("path")
    binary_sha = record.get("sha256")
    linkage = record.get("linkage")
    if not isinstance(binary_path, str) or not Path(binary_path).is_file():
        raise VerificationError(f"runtime evidence is missing {binary_label} binary path")
    if not isinstance(binary_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", binary_sha):
        raise VerificationError(f"runtime evidence is missing {binary_label} binary SHA256")
    if sha256_file(Path(binary_path)) != binary_sha:
        raise VerificationError(f"{binary_label} binary changed after identity capture")
    if resolution not in ("binary-linkage",) and not runtime.get("linked_runtime_path"):
        raise VerificationError("runtime was resolved from a cache without proving binary linkage")
    if not isinstance(linkage, dict) or linkage.get("linkage_verified") is not True:
        raise VerificationError(f"{binary_label} binary linkage to the pinned runtime was not verified")


def bundle_tool_command(arguments: list[object], cargo: str) -> list[object]:
    binary = target_binary("tldr_subset")
    if binary.is_file():
        return [binary, *arguments]
    return [
        cargo,
        "run",
        "--locked",
        "--offline",
        "--features",
        "dev",
        "--bin",
        "tldr_subset",
        "--",
        *arguments,
    ]


def network_sandbox_blocks_loopback_listener(policy: str) -> bool:
    return (
        "sandbox-exec" in policy
        or "unshare --net" in policy
        or "Linux iptables" in policy
        or "Windows program-specific" in policy
    )


def network_probe_evidence(*, required: bool) -> dict[str, object]:
    state_value = os.environ.get("ASKMAN_CI_NETWORK_PROBE_STATE", "").strip()
    if not state_value:
        if required:
            raise VerificationError("network isolation requires an actual probe state file")
        return {"validated": False}
    state_path = Path(state_value)
    if not state_path.is_file():
        raise VerificationError(f"network isolation probe state is missing: {state_path}")
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise VerificationError(f"network isolation probe state is invalid: {state_path}") from error
    if payload.get("connections") != 0:
        raise VerificationError(f"network isolation probe recorded an accepted connection: {payload}")
    return {
        "validated": True,
        "state_path": str(state_path),
        "connections": payload.get("connections"),
        "policy": os.environ.get("ASKMAN_CI_NETWORK_POLICY"),
    }


def write_verification_evidence(
    report_dir: Path,
    bundle: Path,
    manifest: dict[str, object],
    cargo: str,
    status: str,
    *,
    shipping_binary: Path | None = None,
    candidate_binary: Path | None = None,
    strict_runtime: bool = False,
) -> None:
    manifest_path = bundle / "manifest.json"
    write_json(
        report_dir / "release-benchmark-inputs.json",
        {
            "freeze_manifest": "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json",
            "inputs": benchmark_digests(),
        },
    )
    native_runtime = runtime_metadata(
        {
            "shipping": shipping_binary,
            "candidate": candidate_binary,
        }
    )
    if strict_runtime:
        require_runtime_identity(
            native_runtime,
            expected_version=os.environ.get("ORT_EXPECTED_VERSION")
            or os.environ.get("ORT_VERSION"),
        )
    write_json(
        report_dir / "runtime-metadata.json",
        {
            "verification_status": status,
            "code_revision": git_revision(),
            "cargo": command_version(cargo),
            "rustc": command_version("rustc"),
            "python": sys.version,
            "platform": platform.platform(),
            "system": platform.system(),
            "machine": platform.machine(),
            "network_policy": os.environ.get(
                "ASKMAN_CI_NETWORK_POLICY", "not-enforced-by-runner"
            ),
            "network_isolation_enforced": bool(
                os.environ.get("ASKMAN_CI_NETWORK_POLICY")
            ),
            "network_probe": network_probe_evidence(required=False),
            "native_runtime": native_runtime,
            "onnx_runtime": native_runtime["onnx_runtime"],
            "shipping_binary": native_runtime["binaries"].get("shipping"),
            "bundle": {
                "bundle_id": manifest["bundle_id"],
                "manifest_sha256": sha256_file(manifest_path),
                "components": {
                    key: {
                        "path": manifest[key]["path"],
                        "sha256": manifest[key]["sha256"],
                        "size_bytes": manifest[key]["size_bytes"],
                    }
                    for key in ("corpus", "lexical_index", "dense_index")
                },
            },
        },
    )


def build_and_validate_bundle(
    work_dir: Path,
    report_dir: Path,
    cargo: str,
    *,
    bundle_name: str = "matching-bundle",
    source_manifest: Path | None = None,
    log_prefix: str = "bundle",
) -> tuple[Path, dict[str, object]]:
    bundle = work_dir / bundle_name
    source_manifest = source_manifest or ROOT / "tests/fixtures/tldr-full-corpus/manifest.json"
    if not bundle.exists():
        run_logged(
            f"{log_prefix}-build",
            bundle_tool_command(
                [
                    "bundle-build",
                    "--manifest",
                    source_manifest,
                    "--snapshot",
                    ROOT / "tests/fixtures/tldr-full-corpus",
                    "--model-cache",
                    model_cache_path(work_dir),
                    "--output",
                    bundle,
                    "--cli-compatibility",
                    f"askman={package_version()}",
                ],
                cargo,
            ),
            report_dir,
            allow_published_bundle_after_abort=True,
        )
    run_logged(
        f"{log_prefix}-validate",
        bundle_tool_command(["bundle-validate", "--bundle", bundle], cargo),
        report_dir,
    )

    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    write_json(report_dir / "bundle-manifest.json", manifest)
    return bundle, manifest


def create_bundle_archive(bundle: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    # The lifecycle server only needs a valid gzip stream. Avoid spending
    # runner CPU recompressing the already-compressed model asset.
    with tarfile.open(archive_path, "w:gz", compresslevel=0) as archive:
        for path in sorted(bundle.rglob("*")):
            archive.add(
                path,
                arcname=path.relative_to(bundle).as_posix(),
                recursive=False,
            )


def create_partial_bundle_archive(bundle: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the failure fixture deterministic across OSes: a valid archive
    # missing required bundle components fails validation without asking each
    # platform's native gzip/tar stack to interpret a cut-off gzip stream.
    with tarfile.open(archive_path, "w:gz", compresslevel=0) as archive:
        archive.add(bundle / "manifest.json", arcname="manifest.json", recursive=False)


def create_checksum_invalid_bundle_archive(bundle: Path, archive_path: Path) -> None:
    """Create a structurally valid archive with a deliberately bad DB digest."""

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz", compresslevel=0) as archive:
        for path in sorted(bundle.rglob("*")):
            relative = path.relative_to(bundle).as_posix()
            if path.is_dir():
                archive.add(path, arcname=relative, recursive=False)
                continue
            if relative == "matching.db":
                data = bytearray(path.read_bytes())
                if not data:
                    raise VerificationError("cannot corrupt an empty matching database")
                data[-1] ^= 0x01
                info = archive.gettarinfo(path, arcname=relative)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            else:
                archive.add(path, arcname=relative, recursive=False)


def bundle_tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_dir():
            digest.update(b"d\0" + relative + b"\0")
            continue
        digest.update(b"f\0" + relative + b"\0")
        digest.update(sha256_file(path).encode("ascii"))
    return digest.hexdigest()


def storage_name(bundle_id: str) -> str:
    """Mirror BundleStore's deterministic on-disk ID encoding for assertions."""

    return "".join(
        character
        if character.isascii() and (character.isalnum() or character in ".-_")
        else f"%{ord(character):02x}"
        for character in bundle_id
    )


def lifecycle_query(
    askman: Path,
    environment: dict[str, str],
    report_dir: Path,
    label: str,
) -> str:
    """Run a normal query while the release endpoint is deliberately unreachable."""

    offline_environment = dict(environment)
    offline_environment["ASKMAN_RELEASE_BASE_URL"] = "http://127.0.0.1:1"
    output = run_logged(
        label,
        [askman, "--linux", "search", "patterns", "files"],
        report_dir,
        environment=offline_environment,
    )
    if not output.strip():
        raise VerificationError(f"{label} returned no offline query output")
    return output


def assert_failed_update_preserved(
    *,
    askman: Path,
    environment: dict[str, str],
    report_dir: Path,
    state_path: Path,
    expected_state: bytes,
    bundle_paths: dict[str, Path],
    bundle_digests: dict[str, str],
    label: str,
) -> None:
    run_logged(label, [askman, "update"], report_dir, environment=environment, expect_failure=True)
    if state_path.read_bytes() != expected_state:
        raise VerificationError(f"{label} changed active-bundle.json")
    for bundle_id, path in bundle_paths.items():
        if path.is_symlink() or not path.is_dir():
            raise VerificationError(f"{label} removed stored bundle {bundle_id}")
        if bundle_tree_digest(path) != bundle_digests[bundle_id]:
            raise VerificationError(f"{label} changed stored bundle {bundle_id}")
    leftovers = [
        path.name
        for path in bundle_paths[next(iter(bundle_paths))].parent.iterdir()
        if path.name.startswith((".bundle-", ".download-"))
    ]
    if leftovers:
        raise VerificationError(f"{label} left staging artifacts: {leftovers}")


def resolve_shipping_binary(
    explicit: Path | None = None,
    *,
    require_release: bool = False,
) -> tuple[Path, str]:
    """Resolve the exact CLI binary used for lifecycle and query verification."""

    if explicit is not None:
        binary = explicit.expanduser()
        if not binary.is_absolute():
            binary = ROOT / binary
        binary = binary.resolve()
        if not binary.is_file():
            raise VerificationError(f"shipping binary does not exist: {binary}")
        kind = "release" if "release" in binary.parts else "explicit"
        if require_release and kind != "release":
            raise VerificationError(f"production verification requires a release binary: {binary}")
        return binary, kind

    release = target_binary("askman", "release")
    if release.is_file():
        return release, "release"
    if require_release:
        raise VerificationError(f"production shipping binary was not built: {release}")

    debug = target_binary("askman")
    if debug.is_file():
        return debug, "debug"
    raise VerificationError(f"shipping binary was not built: {release}")


def prepare_lifecycle(
    work_dir: Path,
    report_dir: Path,
    *,
    shipping_binary: Path | None = None,
    require_release_binary: bool = False,
) -> None:
    validate_provisioned_assets(work_dir, report_dir)
    cargo = os.environ.get("CARGO", "cargo")
    bundle, manifest = build_and_validate_bundle(work_dir, report_dir, cargo)

    # Build a second valid bundle with a distinct source revision. This keeps
    # the lifecycle check honest: update and rollback move between immutable
    # IDs produced by the real builder, rather than repeatedly accepting the
    # same idempotent release asset.
    second_source_manifest = work_dir / "lifecycle-source-v2-manifest.json"
    second_source = json.loads(
        (ROOT / "tests/fixtures/tldr-full-corpus/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    second_source["source"]["revision"] = "fixture-tldr-full-corpus-v2"
    second_source["source"]["url"] = "https://github.com/tldr-pages/tldr/tree/fixture-v2"
    write_json(second_source_manifest, second_source)
    second_bundle, second_manifest = build_and_validate_bundle(
        work_dir,
        report_dir,
        cargo,
        bundle_name="matching-bundle-v2",
        source_manifest=second_source_manifest,
        log_prefix="bundle-v2",
    )
    first_id = str(manifest["bundle_id"])
    second_id = str(second_manifest["bundle_id"])
    if first_id == second_id:
        raise VerificationError("lifecycle fixtures did not produce distinct bundle IDs")
    askman, shipping_kind = resolve_shipping_binary(
        shipping_binary,
        require_release=require_release_binary,
    )
    write_verification_evidence(
        report_dir,
        bundle,
        manifest,
        cargo,
        "lifecycle-running",
        shipping_binary=askman,
        strict_runtime=require_release_binary,
    )

    release_root = work_dir / "release" / f"v{package_version()}"
    release_root.mkdir(parents=True, exist_ok=True)

    def release_variant(name: str, variant_bundle: Path) -> dict[str, Path]:
        variant_root = release_root / name
        variant_root.mkdir(parents=True, exist_ok=True)
        manifest_path = variant_root / "matching-bundle-manifest.json"
        manifest_path.write_bytes((variant_bundle / "manifest.json").read_bytes())
        archive_path = variant_root / "matching-bundle.tar.gz"
        create_bundle_archive(variant_bundle, archive_path)
        return {"manifest": manifest_path, "archive": archive_path}

    print("[ci-offline] creating lifecycle release archives", flush=True)
    variants = {
        "first": release_variant("first", bundle),
        "second": release_variant("second", second_bundle),
    }
    partial_archive_path = release_root / "partial.tar.gz"
    create_partial_bundle_archive(bundle, partial_archive_path)
    checksum_invalid_archive_path = release_root / "checksum-invalid.tar.gz"
    create_checksum_invalid_bundle_archive(second_bundle, checksum_invalid_archive_path)
    incompatible_manifest_path = release_root / "incompatible-manifest.json"
    incompatible_manifest = json.loads(
        variants["first"]["manifest"].read_text(encoding="utf-8")
    )
    incompatible_manifest["cli_compatibility"] = "askman=999.999.999"
    write_json(incompatible_manifest_path, incompatible_manifest)
    variants.update(
        {
            "partial": {
                "manifest": variants["first"]["manifest"],
                "archive": partial_archive_path,
            },
            "checksum-invalid": {
                "manifest": variants["second"]["manifest"],
                "archive": checksum_invalid_archive_path,
            },
            "mixed": {
                "manifest": variants["first"]["manifest"],
                "archive": variants["second"]["archive"],
            },
            "incompatible": {
                "manifest": incompatible_manifest_path,
                "archive": variants["first"]["archive"],
            },
        }
    )
    print("[ci-offline] lifecycle release archives ready", flush=True)

    data_dir = work_dir / "lifecycle-data"
    if data_dir.exists():
        raise VerificationError(f"refusing to reuse lifecycle data directory: {data_dir}")

    serve_mode = "first"

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            asset = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
            if asset in ("matching-bundle-manifest.json", "matching-bundle.tar.gz"):
                key = "manifest" if asset.endswith("manifest.json") else "archive"
                path = variants[serve_mode][key]
                payload = path.read_bytes()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/json" if key == "manifest" else "application/gzip",
                )
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            self.send_error(http.HTTPStatus.NOT_FOUND)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    handler = functools.partial(QuietHandler, directory=str(work_dir / "release"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    # Handler threads serve disposable local test traffic; do not make
    # server_close wait forever for a client that already abandoned a body.
    server.block_on_close = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[ci-offline] lifecycle server listening on {server.server_port}", flush=True)
    release_base_url = f"http://127.0.0.1:{server.server_port}"
    lifecycle_environment = {
        "ASKMAN_DATA_DIR": str(data_dir),
        "ASKMAN_RELEASE_BASE_URL": release_base_url,
        "CLICOLOR_FORCE": "0",
        "NO_COLOR": "1",
    }
    state_path = data_dir / "active-bundle.json"
    lifecycle_queries: dict[str, str] = {}
    state_after_setup: bytes | None = None
    state_after_update: bytes | None = None
    bundle_paths = {
        first_id: data_dir / "bundles" / storage_name(first_id),
        second_id: data_dir / "bundles" / storage_name(second_id),
    }
    try:
        run_logged(
            "lifecycle-setup", [askman, "setup"], report_dir, environment=lifecycle_environment
        )
        if not state_path.is_file():
            raise VerificationError("askman setup did not create active-bundle.json")
        state_after_setup = state_path.read_bytes()
        setup_state = json.loads(state_after_setup)
        if setup_state["active_bundle_id"] != first_id or setup_state["previous_bundle_id"] is not None:
            raise VerificationError("setup did not activate the first immutable bundle")
        lifecycle_queries["after_setup"] = hashlib.sha256(
            lifecycle_query(askman, lifecycle_environment, report_dir, "lifecycle-query-setup").encode()
        ).hexdigest()

        serve_mode = "second"
        run_logged(
            "lifecycle-update", [askman, "update"], report_dir, environment=lifecycle_environment
        )
        if not bundle_paths[first_id].is_dir() or not bundle_paths[second_id].is_dir():
            raise VerificationError("successful update did not retain both immutable bundle IDs")
        state_after_update = state_path.read_bytes()
        update_state = json.loads(state_after_update)
        if update_state["active_bundle_id"] != second_id or update_state["previous_bundle_id"] != first_id:
            raise VerificationError("update did not activate the second immutable bundle")
        bundle_digests = {
            bundle_id: bundle_tree_digest(path)
            for bundle_id, path in bundle_paths.items()
        }
        lifecycle_queries["after_update"] = hashlib.sha256(
            lifecycle_query(askman, lifecycle_environment, report_dir, "lifecycle-query-update").encode()
        ).hexdigest()

        for failure_mode in ("partial", "checksum-invalid", "mixed", "incompatible"):
            serve_mode = failure_mode
            assert_failed_update_preserved(
                askman=askman,
                environment=lifecycle_environment,
                report_dir=report_dir,
                state_path=state_path,
                expected_state=state_after_update,
                bundle_paths=bundle_paths,
                bundle_digests=bundle_digests,
                label=f"lifecycle-failed-update-{failure_mode}",
            )

        # Rollback reads only the active state and immutable local bundles. It
        # remains a real CLI transition even with the release endpoint down.
        lifecycle_queries["after_failed_updates"] = hashlib.sha256(
            lifecycle_query(askman, lifecycle_environment, report_dir, "lifecycle-query-preserved").encode()
        ).hexdigest()
        rollback_environment = dict(lifecycle_environment)
        rollback_environment["ASKMAN_RELEASE_BASE_URL"] = "http://127.0.0.1:1"
        run_logged("lifecycle-rollback", [askman, "rollback"], report_dir, environment=rollback_environment)
        rollback_state = json.loads(state_path.read_text(encoding="utf-8"))
        if rollback_state["active_bundle_id"] != first_id or rollback_state["previous_bundle_id"] != second_id:
            raise VerificationError("rollback did not restore the first immutable bundle")
        lifecycle_queries["after_rollback"] = hashlib.sha256(
            lifecycle_query(askman, rollback_environment, report_dir, "lifecycle-query-rollback").encode()
        ).hexdigest()
    finally:
        print("[ci-offline] stopping lifecycle server", flush=True)
        shutdown_thread = threading.Thread(target=server.shutdown, daemon=True)
        shutdown_thread.start()
        shutdown_thread.join(timeout=5)
        if shutdown_thread.is_alive():
            print(
                "[ci-offline] lifecycle server shutdown did not return; closing listener",
                flush=True,
            )

        close_thread = threading.Thread(target=server.server_close, daemon=True)
        close_thread.start()
        close_thread.join(timeout=5)
        if close_thread.is_alive():
            print("[ci-offline] lifecycle server close did not return", flush=True)

        thread.join(timeout=5)
        if shutdown_thread.is_alive() or close_thread.is_alive() or thread.is_alive():
            raise VerificationError("lifecycle server teardown did not finish within 5 seconds")

    write_json(
        report_dir / "lifecycle.json",
        {
            "active_bundle_id": first_id,
            "bundle_ids": {"first": first_id, "second": second_id},
            "data_dir": str(data_dir),
            "release_base_url": release_base_url,
            "failed_update_preserved_active_state": True,
            "failed_update_modes": ["partial", "checksum-invalid", "mixed", "incompatible"],
            "offline_query_sha256": lifecycle_queries,
            "rollback_restored_previous_bundle": True,
            "server_stopped_before_query": True,
            "shipping_binary": str(askman),
            "shipping_binary_kind": shipping_kind,
        },
    )


def parse_shipping_json(output: str, label: str) -> list[dict[str, object]]:
    """Parse the shipping CLI's JSON output without accepting human text."""

    text = output.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        # A native runtime can emit a diagnostic line before the JSON payload.
        # Accept only a payload that decodes to the CI array or historical
        # object; never treat arbitrary non-empty text as a passing query.
        value = None
        decoder = json.JSONDecoder()
        for match in re.finditer(r"[\[{]", text):
            try:
                candidate = decoder.raw_decode(text[match.start() :])[0]
            except json.JSONDecodeError:
                continue
            if (isinstance(candidate, list) and all(isinstance(item, dict) for item in candidate)) or (
                isinstance(candidate, dict)
                and isinstance(candidate.get("results"), list)
                and all(isinstance(item, dict) for item in candidate["results"])
            ):
                value = candidate
                break
        if value is None:
            raise VerificationError(f"{label} did not emit shipping CLI JSON: {error}") from error
    # Preserve the historical public `-j/--json` object while accepting the
    # versioned CI array emitted by `--ci-json-v1`.
    if isinstance(value, dict) and isinstance(value.get("results"), list):
        value = value["results"]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise VerificationError(f"{label} emitted an invalid shipping CLI JSON result list")
    return value


def verify(
    work_dir: Path,
    report_dir: Path,
    *,
    shipping_binary: Path | None = None,
    require_release_binary: bool = False,
) -> None:
    validate_provisioned_assets(work_dir, report_dir)
    cargo = os.environ.get("CARGO", "cargo")
    bundle, manifest = build_and_validate_bundle(work_dir, report_dir, cargo)
    lifecycle_path = report_dir / "lifecycle.json"
    if not lifecycle_path.is_file():
        raise VerificationError(f"missing lifecycle preparation record: {lifecycle_path}")
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    required_failure_modes = {"partial", "checksum-invalid", "mixed", "incompatible"}
    if set(lifecycle.get("failed_update_modes", [])) != required_failure_modes:
        raise VerificationError("lifecycle evidence is missing a failed-update mode")
    if lifecycle.get("rollback_restored_previous_bundle") is not True:
        raise VerificationError("lifecycle evidence is missing rollback coverage")
    required_query_states = {"after_setup", "after_update", "after_failed_updates", "after_rollback"}
    if set(lifecycle.get("offline_query_sha256", {})) != required_query_states:
        raise VerificationError("lifecycle evidence is missing an offline query state")
    query_environment = {
        "ASKMAN_DATA_DIR": lifecycle["data_dir"],
        "ASKMAN_RELEASE_BASE_URL": lifecycle["release_base_url"],
        "CLICOLOR_FORCE": "0",
        "NO_COLOR": "1",
    }
    network_policy = os.environ.get("ASKMAN_CI_NETWORK_POLICY", "").strip()
    if not network_policy or network_policy == "not-enforced-by-runner":
        raise VerificationError(
            "offline verification requires an OS-enforced ASKMAN_CI_NETWORK_POLICY"
        )
    if not any(
        network_policy.startswith(prefix)
        for prefix in ("Linux iptables", "macOS sandbox-exec", "Windows program-specific")
    ):
        raise VerificationError(f"unrecognized network isolation policy: {network_policy}")
    network_probe_evidence(required=True)

    selected_shipping = shipping_binary
    if selected_shipping is None and lifecycle.get("shipping_binary"):
        selected_shipping = Path(str(lifecycle["shipping_binary"]))
    shipping, shipping_kind = resolve_shipping_binary(
        selected_shipping,
        require_release=require_release_binary,
    )
    if require_release_binary and lifecycle.get("shipping_binary_kind") != "release":
        raise VerificationError("lifecycle was not prepared with the production release binary")
    write_verification_evidence(
        report_dir,
        bundle,
        manifest,
        cargo,
        "running",
        shipping_binary=shipping,
        strict_runtime=require_release_binary,
    )

    lifecycle_test_command = [
        cargo,
        "test",
        "--locked",
        "--offline",
        "--features",
        "dev",
        "--lib",
        "bundle::tests",
    ]
    network_policy = os.environ.get("ASKMAN_CI_NETWORK_POLICY", "")
    if network_sandbox_blocks_loopback_listener(network_policy):
        # This test deliberately binds a loopback listener to prove that the
        # active-bundle path does not contact the release URL. Network
        # isolation correctly denies that listener setup before the test can
        # exercise the no-contact assertion. The normal matrix test job runs
        # the complete module before entering the sandbox.
        lifecycle_test_command.extend(
            ["--", "--skip", "active_bundle_lookup_does_not_contact_release_base_url"]
        )
    run_logged("bundle-lifecycle-tests", lifecycle_test_command, report_dir)

    query_records: list[dict[str, object]] = []
    for policy_name, flags, query, expected_platform, expected_source_path in TARGET_QUERIES:
        output = run_logged(
            f"shipping-query-{policy_name}",
            [shipping, "--ci-json-v1", *flags, *query.split()],
            report_dir,
            environment=query_environment,
        )
        results = parse_shipping_json(output, f"shipping-query-{policy_name}")
        if not results:
            raise VerificationError(f"shipping-query-{policy_name} returned no JSON results")
        top = results[0]
        if top.get("platform") != expected_platform:
            raise VerificationError(
                f"shipping-query-{policy_name} top platform is {top.get('platform')!r}, "
                f"expected {expected_platform!r}"
            )
        if top.get("source_path") != expected_source_path:
            raise VerificationError(
                f"shipping-query-{policy_name} top source is {top.get('source_path')!r}, "
                f"expected {expected_source_path!r}"
            )
        query_records.append(
            {
                "policy": policy_name,
                "flags": list(flags),
                "query": query,
                "expected_top_platform": expected_platform,
                "expected_top_source_path": expected_source_path,
                "top_platform": top["platform"],
                "top_source_path": top["source_path"],
                "result_count": len(results),
                "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                "binary": str(shipping),
                "binary_kind": shipping_kind,
            }
        )
    write_json(report_dir / "queries.json", query_records)

    write_verification_evidence(
        report_dir,
        bundle,
        manifest,
        cargo,
        "passed",
        shipping_binary=shipping,
        strict_runtime=require_release_binary,
    )
    print(f"Offline verification passed for {len(TARGET_QUERIES)} target policies")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("provision", "prepare", "verify", "runtime"))
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--shipping-binary", type=Path)
    parser.add_argument("--require-release-binary", action="store_true")
    parser.add_argument("--binary", type=Path, help="binary to identify during the runtime phase")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.phase == "provision":
            provision(args.work_dir, args.report_dir)
        elif args.phase == "prepare":
            prepare_lifecycle(
                args.work_dir,
                args.report_dir,
                shipping_binary=args.shipping_binary,
                require_release_binary=args.require_release_binary,
            )
        elif args.phase == "verify":
            verify(
                args.work_dir,
                args.report_dir,
                shipping_binary=args.shipping_binary,
                require_release_binary=args.require_release_binary,
            )
        else:
            binary = args.binary or args.shipping_binary or target_binary("askman", "release")
            native_runtime = runtime_metadata({"shipping": binary})
            require_runtime_identity(
                native_runtime,
                expected_version=os.environ.get("ORT_EXPECTED_VERSION")
                or os.environ.get("ORT_VERSION"),
            )
            write_json(
                args.report_dir / "runtime-metadata.json",
                {
                    "verification_status": "runtime-identity",
                    "code_revision": git_revision(),
                    "native_runtime": native_runtime,
                    "onnx_runtime": native_runtime["onnx_runtime"],
                    "shipping_binary": native_runtime["binaries"].get("shipping"),
                },
            )
    except (OSError, ValueError, VerificationError) as error:
        print(f"CI offline verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
