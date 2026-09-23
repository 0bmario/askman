#!/usr/bin/env python3
"""Download and verify the exact shared ONNX Runtime used by a build.

The release workflow must not depend on ``ort-sys``'s cache-backed download.
Every supported release target has an explicit Microsoft archive, archive
digest, runtime digest, and license/notice digest here.  The verified archive
is extracted into a runner-temporary directory and its root is exported for
the following build steps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import tarfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.20.0"
RELEASE_BASE = "https://github.com/microsoft/onnxruntime/releases/download/v1.20.0"


RUNTIME_ASSETS: dict[str, dict[str, object]] = {
    "x86_64-unknown-linux-gnu": {
        "os": "Linux",
        "machines": ("x86_64", "amd64"),
        "archive_name": "onnxruntime-linux-x64-1.20.0.tgz",
        "archive_sha256": "aa70d48b22e264b82e83f63245b51ddc9a47ae4a3a66903efaff1ba68b7b5930",
        "root_name": "onnxruntime-linux-x64-1.20.0",
        "library_path": "lib/libonnxruntime.so.1.20.0",
        "library_name": "libonnxruntime.so.1.20.0",
        "library_sha256": "6097fe8cedc8b5b3c8e107e9c2acf04eb50f58f0f045e3d7c5c50ead38112c72",
        "license_path": "LICENSE",
        "license_sha256": "2f07c72751aed99790b8a4869cf2311df85a860b22ded05fa22803587a48922c",
        "notice_path": "ThirdPartyNotices.txt",
        "notice_sha256": "cf7342f7ba482ef715ae58f5f497a8d3564fa255164175aea324cd293c5701a0",
        "loader_variable": "LD_LIBRARY_PATH",
    },
    "x86_64-apple-darwin": {
        "os": "Darwin",
        "machines": ("x86_64", "amd64"),
        "archive_name": "onnxruntime-osx-x86_64-1.20.0.tgz",
        "archive_sha256": "d28e603b47b74050f2c30a7069bf3fb371cfba7205d7771f22cabc7b02953757",
        "root_name": "onnxruntime-osx-x86_64-1.20.0",
        "library_path": "lib/libonnxruntime.1.20.0.dylib",
        "library_name": "libonnxruntime.1.20.0.dylib",
        "library_sha256": "542ffd4568821088ff3e42a3aa19c37dbbd73b522bfe58505520de332e581b4d",
        "license_path": "LICENSE",
        "license_sha256": "2f07c72751aed99790b8a4869cf2311df85a860b22ded05fa22803587a48922c",
        "notice_path": "ThirdPartyNotices.txt",
        "notice_sha256": "cf7342f7ba482ef715ae58f5f497a8d3564fa255164175aea324cd293c5701a0",
        "loader_variable": "DYLD_LIBRARY_PATH",
    },
    "aarch64-apple-darwin": {
        "os": "Darwin",
        "machines": ("arm64", "aarch64"),
        "archive_name": "onnxruntime-osx-arm64-1.20.0.tgz",
        "archive_sha256": "2bcfaafa9ff0a3a94f78e3af2f135ffde5bb2d79b08e83a50dbc450b0d20ddae",
        "root_name": "onnxruntime-osx-arm64-1.20.0",
        "library_path": "lib/libonnxruntime.1.20.0.dylib",
        "library_name": "libonnxruntime.1.20.0.dylib",
        "library_sha256": "d8be733cb8dd097cfe2b21e069a7462b5ff561625141d9c4b98d866f15bfb852",
        "license_path": "LICENSE",
        "license_sha256": "2f07c72751aed99790b8a4869cf2311df85a860b22ded05fa22803587a48922c",
        "notice_path": "ThirdPartyNotices.txt",
        "notice_sha256": "cf7342f7ba482ef715ae58f5f497a8d3564fa255164175aea324cd293c5701a0",
        "loader_variable": "DYLD_LIBRARY_PATH",
    },
    "x86_64-pc-windows-msvc": {
        "os": "Windows",
        "machines": ("amd64", "x86_64", "x64"),
        "archive_name": "onnxruntime-win-x64-1.20.0.zip",
        "archive_sha256": "b372de85cedd9387a0d4386b982265e8420e5bcc2f29394317e76525b832942e",
        "root_name": "onnxruntime-win-x64-1.20.0",
        "library_path": "lib/onnxruntime.dll",
        "library_name": "onnxruntime.dll",
        "library_sha256": "52f8ebe8f08f369a44fed6d1cb680c7c89169795e1c2949ee25b88b538ef0948",
        "license_path": "LICENSE",
        "license_sha256": "c250d6278f0b47a6439fb7592b08b58a55eb9f535aa49a1db63211c3f982b674",
        "notice_path": "ThirdPartyNotices.txt",
        "notice_sha256": "fac5bb85f568b38fd8f3a6aea32737985841f23a1a43e9ce952f79474f883aa9",
        "loader_variable": "PATH",
    },
}


class ProvisionError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_path(destination: Path, name: str) -> Path:
    target = (destination / name).resolve()
    if not target.is_relative_to(destination.resolve()):
        raise ProvisionError(f"archive entry escapes extraction root: {name}")
    return target


def extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        for member in members:
            target = _safe_member_path(destination, member.name)
            if member.issym() or member.islnk():
                link_target = _safe_member_path(target.parent, member.linkname)
                if not link_target.is_relative_to(destination.resolve()):
                    raise ProvisionError(f"archive link escapes extraction root: {member.name}")
            elif not (member.isfile() or member.isdir()):
                raise ProvisionError(f"unsupported archive entry: {member.name}")
        stream.extractall(destination)


def extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as stream:
        for member in stream.infolist():
            _safe_member_path(destination, member.filename)
            if member.is_dir():
                continue
            destination_path = _safe_member_path(destination, member.filename)
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            destination_path.write_bytes(stream.read(member))


def download_verified(url: str, destination: Path, expected_sha256: str) -> None:
    request = Request(url, headers={"User-Agent": "askman-release-runtime-provision/1"})
    with urlopen(request, timeout=1800) as response:
        payload = response.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    actual = sha256_file(destination)
    if actual != expected_sha256:
        raise ProvisionError(
            f"downloaded ONNX Runtime archive SHA differs: expected {expected_sha256}, got {actual}"
        )


def assert_host(target: str, asset: dict[str, object]) -> None:
    system = platform.system()
    machine = platform.machine().lower()
    expected_system = str(asset["os"])
    expected_machines = {str(value).lower() for value in asset["machines"]}
    if system != expected_system or machine not in expected_machines:
        raise ProvisionError(
            f"target {target} requires native {expected_system}/{sorted(expected_machines)}, "
            f"got {system}/{machine}"
        )


def write_github_env(path: Path, root: Path, library_directory: Path, asset: dict[str, object]) -> dict[str, str]:
    existing_path = os.environ.get("PATH", "")
    if asset["loader_variable"] == "PATH":
        loader_value = os.pathsep.join((str(library_directory), existing_path))
    else:
        loader_value = str(library_directory)
    values = {
        "ORT_EXPECTED_VERSION": VERSION,
        "ORT_LIB_LOCATION": str(root),
        "ORT_LIBRARY_PATH": str(library_directory),
        "ORT_ROOT": str(root),
        "LD_LIBRARY_PATH": loader_value if asset["loader_variable"] == "LD_LIBRARY_PATH" else "",
        "DYLD_LIBRARY_PATH": loader_value if asset["loader_variable"] == "DYLD_LIBRARY_PATH" else "",
        "PATH": loader_value if asset["loader_variable"] == "PATH" else existing_path,
        "ASKMAN_ORT_RUNTIME_ROOT": str(root),
    }
    with path.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")
    return values


def provision(target: str, work_dir: Path, report_path: Path, github_env: Path | None) -> dict[str, object]:
    try:
        asset = RUNTIME_ASSETS[target]
    except KeyError as error:
        raise ProvisionError(f"unsupported release target: {target}") from error
    assert_host(target, asset)
    work_dir.mkdir(parents=True, exist_ok=True)
    archive = work_dir / str(asset["archive_name"])
    download_verified(
        f"{RELEASE_BASE}/{asset['archive_name']}",
        archive,
        str(asset["archive_sha256"]),
    )
    extracted_parent = work_dir / "extracted"
    if extracted_parent.exists():
        shutil.rmtree(extracted_parent)
    extracted_parent.mkdir()
    if archive.suffix == ".zip":
        extract_zip(archive, extracted_parent)
    else:
        extract_tar(archive, extracted_parent)
    root = extracted_parent / str(asset["root_name"])
    if not root.is_dir():
        raise ProvisionError(f"verified archive has no expected root: {root}")
    library = root / str(asset["library_path"])
    if not library.is_file() or sha256_file(library) != asset["library_sha256"]:
        raise ProvisionError(f"ONNX Runtime library identity mismatch: {library}")
    license_path = root / str(asset["license_path"])
    notice_path = root / str(asset["notice_path"])
    for path, key in ((license_path, "license_sha256"), (notice_path, "notice_sha256")):
        if not path.is_file() or sha256_file(path) != asset[key]:
            raise ProvisionError(f"ONNX Runtime license/notice identity mismatch: {path}")
    env_values = write_github_env(github_env, root, library.parent, asset) if github_env else {}
    report = {
        "schema_version": 1,
        "target": target,
        "host": {"system": platform.system(), "machine": platform.machine()},
        "version": VERSION,
        "archive": {
            "name": asset["archive_name"],
            "url": f"{RELEASE_BASE}/{asset['archive_name']}",
            "path": str(archive),
            "sha256": asset["archive_sha256"],
        },
        "runtime": {
            "root": str(root),
            "library_path": str(library),
            "library_name": asset["library_name"],
            "library_sha256": asset["library_sha256"],
            "loader_variable": asset["loader_variable"],
            "library_directory": str(library.parent),
        },
        "licenses": [
            {"path": str(license_path), "name": "LICENSE", "sha256": asset["license_sha256"]},
            {
                "path": str(notice_path),
                "name": "ThirdPartyNotices.txt",
                "sha256": asset["notice_sha256"],
            },
        ],
        "github_env": env_values,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=sorted(RUNTIME_ASSETS), required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args()
    try:
        report = provision(args.target, args.work_dir.resolve(), args.report.resolve(), args.github_env)
    except (OSError, ValueError, ProvisionError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise SystemExit(f"ONNX Runtime provisioning failed: {error}") from error
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
