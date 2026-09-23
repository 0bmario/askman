#!/usr/bin/env python3
"""Build a self-contained release archive around one shipping binary.

The archive is deliberately assembled only after the binary's native runtime
identity has been recorded.  The loader path is then made relative to the
archive contents, so an extracted asset does not depend on a CI cache path.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import NoReturn


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fail(message: str) -> "NoReturn":
    raise SystemExit(message)


def run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        fail(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}")
    return completed.stdout


def runtime_from_report(report_path: Path) -> tuple[Path, dict[str, object], dict[str, object]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    runtime = report.get("onnx_runtime")
    if not isinstance(runtime, dict):
        native = report.get("native_runtime")
        runtime = native.get("onnx_runtime") if isinstance(native, dict) else None
    if not isinstance(runtime, dict):
        fail(f"runtime report has no ONNX Runtime identity: {report_path}")
    path = runtime.get("library_path")
    version = runtime.get("version")
    digest = runtime.get("library_sha256")
    if not isinstance(path, str) or not isinstance(version, str) or not isinstance(digest, str):
        fail("runtime report is missing exact linked library path/version/SHA256")
    library = Path(path)
    if not library.is_file() or sha256(library) != digest:
        fail(f"runtime library does not match its recorded SHA256: {library}")
    return library, runtime, report


def verify_provision_report(
    report_path: Path,
    runtime_library: Path,
    runtime: dict[str, object],
) -> list[Path]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    pinned_runtime = report.get("runtime")
    archive = report.get("archive")
    licenses = report.get("licenses")
    if not isinstance(pinned_runtime, dict) or not isinstance(archive, dict) or not isinstance(licenses, list):
        fail(f"invalid ONNX Runtime provisioning report: {report_path}")
    if pinned_runtime.get("library_sha256") != runtime.get("library_sha256"):
        fail("runtime report does not match the pinned provisioned library SHA256")
    if pinned_runtime.get("library_name") != runtime_library.name:
        fail("runtime report does not match the pinned provisioned library name")
    if not isinstance(archive.get("sha256"), str) or len(archive["sha256"]) != 64:
        fail("runtime provisioning report has no archive SHA256")
    license_paths: list[Path] = []
    expected_license_names = {"LICENSE", "ThirdPartyNotices.txt"}
    observed_license_names: set[str] = set()
    for record in licenses:
        if not isinstance(record, dict):
            fail("runtime provisioning report has an invalid license record")
        path = record.get("path")
        digest = record.get("sha256")
        name = record.get("name")
        if not isinstance(path, str) or not isinstance(digest, str) or not isinstance(name, str):
            fail("runtime provisioning report has an incomplete license record")
        if name not in expected_license_names or name in observed_license_names:
            fail("runtime provisioning report has an unexpected license/notice name")
        license_path = Path(path)
        if not license_path.is_file() or sha256(license_path) != digest:
            fail(f"pinned runtime license/notice changed: {license_path}")
        license_paths.append(license_path)
        observed_license_names.add(name)
    if observed_license_names != expected_license_names:
        fail("runtime provisioning report is missing LICENSE or ThirdPartyNotices.txt")
    return license_paths


def discover_license_files(runtime_library: Path) -> list[Path]:
    candidates: list[Path] = []
    for root in (runtime_library.parent, runtime_library.parent.parent, runtime_library.parent.parent.parent):
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir()):
            if not path.is_file():
                continue
            lower = path.name.lower()
            if lower.startswith("license") or "thirdparty" in lower or "third-party" in lower:
                if path not in candidates:
                    candidates.append(path)
    if not candidates:
        fail(f"pinned ONNX Runtime license/notice was not found near {runtime_library}")
    return candidates


def patch_loader(binary: Path, runtime_library: Path, system: str) -> None:
    runtime_name = runtime_library.name
    if system == "Linux":
        patchelf = shutil.which("patchelf")
        if patchelf is None:
            fail("patchelf is required to make a Linux release archive self-contained")
        run([patchelf, "--set-rpath", "$ORIGIN", str(binary)])
        return
    if system == "Darwin":
        install_name_tool = shutil.which("install_name_tool")
        otool = shutil.which("otool")
        if install_name_tool is None or otool is None:
            fail("install_name_tool and otool are required for a macOS release archive")
        dependencies = run([otool, "-L", str(binary)]).splitlines()[1:]
        for line in dependencies:
            dependency = line.strip().split(" (", 1)[0]
            if "onnxruntime" in dependency and dependency != f"@loader_path/{runtime_name}":
                run([install_name_tool, "-change", dependency, f"@loader_path/{runtime_name}", str(binary)])
        load_commands = run([otool, "-l", str(binary)])
        if "@loader_path" not in load_commands:
            run([install_name_tool, "-add_rpath", "@loader_path", str(binary)])
        return
    if system == "Windows":
        # Windows resolves a DLL beside the executable.  No binary rewrite is
        # needed; the archive places the exact DLL next to askman.exe.
        return
    fail(f"unsupported release platform: {system}")


def archive_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def write_archive(staging: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in sorted(staging.rglob("*")):
                    archive.add(
                        path,
                        arcname=path.relative_to(staging).as_posix(),
                        recursive=False,
                        filter=archive_filter,
                    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--runtime-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--system", default=platform.system())
    parser.add_argument("--license", type=Path, action="append")
    parser.add_argument("--provision-report", type=Path)
    args = parser.parse_args()

    binary = args.binary.resolve()
    if not binary.is_file():
        fail(f"release binary does not exist: {binary}")
    runtime_library, runtime, runtime_report = runtime_from_report(args.runtime_report.resolve())
    if runtime.get("version") != os.environ.get("ORT_EXPECTED_VERSION", runtime.get("version")):
        fail("linked ONNX Runtime version does not match ORT_EXPECTED_VERSION")
    expected_binary = runtime.get("binary_sha256")
    actual_binary = sha256(binary)
    if isinstance(expected_binary, str) and actual_binary != expected_binary:
        fail("release binary does not match runtime report binary SHA256")

    if args.provision_report:
        provisioned_licenses = verify_provision_report(
            args.provision_report.resolve(), runtime_library, runtime
        )
        licenses = [path.resolve() for path in args.license] if args.license else provisioned_licenses
    else:
        licenses = [path.resolve() for path in args.license] if args.license else discover_license_files(runtime_library)
    if any(not path.is_file() for path in licenses):
        fail("release archive license/notice input is missing")

    source_binary_sha256 = actual_binary
    binary_name = binary.name
    with tempfile.TemporaryDirectory(prefix="askman-release-asset-") as directory:
        staging = Path(directory)
        packaged_binary = staging / binary_name
        packaged_runtime = staging / runtime_library.name
        shutil.copy2(binary, packaged_binary)
        shutil.copy2(runtime_library, packaged_runtime)
        patch_loader(packaged_binary, packaged_runtime, args.system)
        packaged_binary_sha256 = sha256(packaged_binary)
        license_dir = staging / "licenses"
        license_dir.mkdir()
        copied_licenses: list[dict[str, str]] = []
        for index, license_path in enumerate(licenses):
            if index == 0:
                name = "onnxruntime-LICENSE.txt"
            else:
                name = f"onnxruntime-notice-{index}.txt"
            destination = license_dir / name
            shutil.copy2(license_path, destination)
            copied_licenses.append({"path": f"licenses/{name}", "sha256": sha256(destination)})
        manifest = {
            "schema_version": 1,
            "binary": {
                "path": binary_name,
                "sha256": packaged_binary_sha256,
                "packaged_sha256": packaged_binary_sha256,
                "source_sha256": source_binary_sha256,
            },
            "onnx_runtime": {
                "version": runtime["version"],
                "library": packaged_runtime.name,
                "sha256": sha256(packaged_runtime),
                "source_path": str(runtime_library),
                "linked_path": runtime.get("library_path"),
            },
            "licenses": copied_licenses,
            "source_runtime_report_sha256": sha256(args.runtime_report.resolve()),
        }
        if args.provision_report:
            manifest["source_runtime_provision_report_sha256"] = sha256(
                args.provision_report.resolve()
            )
        (staging / "release-asset-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        write_archive(staging, args.output.resolve())
    print(json.dumps({"archive": str(args.output.resolve()), "manifest": manifest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
