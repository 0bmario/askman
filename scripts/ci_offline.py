#!/usr/bin/env python3
"""Provision pinned CI assets, then verify the bundle and query path offline."""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import platform
import signal
import shlex
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
    ("common", (), "copy files"),
    ("linux", ("--linux",), "search patterns files"),
    ("osx", ("--osx",), "copy text to clipboard"),
    ("windows", ("--windows",), "print formatted value"),
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
    try:
        output, _ = process.communicate(timeout=COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
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
        if process.stdout is not None:
            process.stdout.close()
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        log_path.write_text(f"$ {rendered}\n\n{output}", encoding="utf-8")
        print(output, end="", flush=True)
        raise VerificationError(
            f"{label} timed out after {COMMAND_TIMEOUT_SECONDS} seconds; see {log_path}"
        ) from error
    return_code = process.returncode
    log_path.write_text(f"$ {rendered}\n\n{output}", encoding="utf-8")
    print(output, end="", flush=True)
    if expect_failure and return_code == 0:
        raise VerificationError(f"{label} unexpectedly succeeded; see {log_path}")
    if not expect_failure and return_code != 0:
        raise VerificationError(
            f"{label} failed with exit status {return_code}; see {log_path}"
        )
    print(f"[ci-offline] {label} completed in {time.monotonic() - started_at:.1f}s", flush=True)
    return output


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
    return "sandbox-exec" in policy or "unshare --net" in policy


def write_verification_evidence(
    report_dir: Path,
    bundle: Path,
    manifest: dict[str, object],
    cargo: str,
    status: str,
) -> None:
    manifest_path = bundle / "manifest.json"
    write_json(
        report_dir / "release-benchmark-inputs.json",
        {
            "freeze_manifest": "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json",
            "inputs": benchmark_digests(),
        },
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
    work_dir: Path, report_dir: Path, cargo: str
) -> tuple[Path, dict[str, object]]:
    bundle = work_dir / "matching-bundle"
    if not bundle.exists():
        run_logged(
            "bundle-build",
            bundle_tool_command(
                [
                    "bundle-build",
                    "--manifest",
                    ROOT / "tests/fixtures/tldr-full-corpus/manifest.json",
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
        )
    run_logged(
        "bundle-validate",
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


def prepare_lifecycle(work_dir: Path, report_dir: Path) -> None:
    validate_provisioned_assets(work_dir, report_dir)
    cargo = os.environ.get("CARGO", "cargo")
    bundle, manifest = build_and_validate_bundle(work_dir, report_dir, cargo)
    write_verification_evidence(report_dir, bundle, manifest, cargo, "lifecycle-running")

    # CI primes the dev-enabled debug binary so the lifecycle can use its
    # disposable loopback release server.
    askman = target_binary("askman")
    if not askman.is_file():
        run_logged(
            "shipping-build",
            [cargo, "build", "--locked", "--offline", "--features", "dev", "--bin", "askman"],
            report_dir,
        )
    if not askman.is_file():
        raise VerificationError(f"shipping binary was not built: {askman}")

    release_root = work_dir / "release" / f"v{package_version()}"
    release_root.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (bundle / "manifest.json").read_bytes()
    (release_root / "matching-bundle-manifest.json").write_bytes(manifest_bytes)
    archive_path = release_root / "matching-bundle.tar.gz"
    print("[ci-offline] creating lifecycle release archive", flush=True)
    create_bundle_archive(bundle, archive_path)
    print("[ci-offline] lifecycle release archive ready", flush=True)
    archive_bytes = archive_path.read_bytes()

    data_dir = work_dir / "lifecycle-data"
    if data_dir.exists():
        raise VerificationError(f"refusing to reuse lifecycle data directory: {data_dir}")

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

    handler = functools.partial(QuietHandler, directory=str(work_dir / "release"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
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
    try:
        run_logged(
            "lifecycle-setup", [askman, "setup"], report_dir, environment=lifecycle_environment
        )
        if not state_path.is_file():
            raise VerificationError("askman setup did not create active-bundle.json")
        state_after_setup = state_path.read_bytes()

        archive_path.write_bytes(archive_bytes[: max(1, len(archive_bytes) // 2)])
        run_logged(
            "lifecycle-failed-update",
            [askman, "update"],
            report_dir,
            environment=lifecycle_environment,
            expect_failure=True,
        )
        if state_path.read_bytes() != state_after_setup:
            raise VerificationError("failed update changed the active bundle state")
        archive_path.write_bytes(archive_bytes)
        run_logged(
            "lifecycle-update", [askman, "update"], report_dir, environment=lifecycle_environment
        )
    finally:
        print("[ci-offline] stopping lifecycle server", flush=True)
        shutdown_thread = threading.Thread(target=server.shutdown, daemon=True)
        shutdown_thread.start()
        shutdown_thread.join(timeout=5)
        server.server_close()
        thread.join(timeout=5)
        if shutdown_thread.is_alive() or thread.is_alive():
            raise VerificationError("lifecycle server did not stop within 5 seconds")

    write_json(
        report_dir / "lifecycle.json",
        {
            "active_bundle_id": manifest["bundle_id"],
            "data_dir": str(data_dir),
            "release_base_url": release_base_url,
            "failed_update_preserved_active_state": True,
            "server_stopped_before_query": True,
        },
    )


def verify(work_dir: Path, report_dir: Path) -> None:
    validate_provisioned_assets(work_dir, report_dir)
    cargo = os.environ.get("CARGO", "cargo")
    bundle, manifest = build_and_validate_bundle(work_dir, report_dir, cargo)
    lifecycle_path = report_dir / "lifecycle.json"
    if not lifecycle_path.is_file():
        raise VerificationError(f"missing lifecycle preparation record: {lifecycle_path}")
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    query_environment = {
        "ASKMAN_DATA_DIR": lifecycle["data_dir"],
        "ASKMAN_RELEASE_BASE_URL": lifecycle["release_base_url"],
        "CLICOLOR_FORCE": "0",
        "NO_COLOR": "1",
    }
    write_verification_evidence(report_dir, bundle, manifest, cargo, "running")

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

    candidate_build = [
        cargo,
        "build",
        "--locked",
        "--offline",
        "--features",
        "dev",
        "--bin",
        "askman_candidate",
    ]
    run_logged("candidate-build", candidate_build, report_dir)
    candidate = ROOT / "target" / "debug" / "askman_candidate"
    if os.name == "nt":
        candidate = candidate.with_suffix(".exe")
    if not candidate.is_file():
        raise VerificationError(f"candidate binary was not built: {candidate}")

    query_records: list[dict[str, object]] = []
    for platform_name, flags, query in TARGET_QUERIES:
        output = run_logged(
            f"query-{platform_name}",
            [candidate, "--bundle", bundle, *flags, *query.split()],
            report_dir,
            environment=query_environment,
        )
        query_records.append(
            {
                "platform": platform_name,
                "flags": list(flags),
                "query": query,
                "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
            }
        )
    shipping = target_binary("askman", "release")
    if not shipping.is_file():
        shipping = target_binary("askman")
    if not shipping.is_file():
        raise VerificationError(f"shipping binary was not built: {shipping}")
    shipping_output = run_logged(
        "shipping-query-linux",
        [shipping, "--linux", "search", "patterns", "files"],
        report_dir,
        environment=query_environment,
    )
    query_records.append(
        {
            "platform": "linux",
            "binary": "askman",
            "query": "search patterns files",
            "output_sha256": hashlib.sha256(shipping_output.encode()).hexdigest(),
        }
    )
    write_json(report_dir / "queries.json", query_records)

    write_verification_evidence(report_dir, bundle, manifest, cargo, "passed")
    print(f"Offline verification passed for {len(TARGET_QUERIES)} target policies")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("provision", "prepare", "verify"))
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.phase == "provision":
            provision(args.work_dir, args.report_dir)
        elif args.phase == "prepare":
            prepare_lifecycle(args.work_dir, args.report_dir)
        else:
            verify(args.work_dir, args.report_dir)
    except (OSError, ValueError, VerificationError) as error:
        print(f"CI offline verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
