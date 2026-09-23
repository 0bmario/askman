#!/usr/bin/env python3
"""Verify that a packaged Askman crate contains code, not mutable data assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import tomllib
from pathlib import Path, PurePosixPath


PACKAGE_NAME = "askman"
REQUIRED_FILES = {
    "Cargo.toml",
    "Cargo.lock",
    "LICENSE",
    "README.md",
    "src/lib.rs",
    "src/main.rs",
}
AUTO_GENERATED_FILES = {".cargo_vcs_info.json", "Cargo.toml.orig"}
FORBIDDEN_SUFFIXES = (".db", ".onnx", ".gguf")
FORBIDDEN_COMPONENTS = {
    ".fastembed_cache",
    ".fastembed_cache_data",
    ".fastembed_cache_models",
    "__pycache__",
    "matching-bundle",
    "model-cache",
    "onnxruntime",
    "target",
}
FORBIDDEN_NAMES = {"commands.db", "matching.db", "model.onnx"}
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class PackageError(ValueError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def relative_member_name(member_name: str, package_prefix: str) -> str:
    if not member_name.startswith(package_prefix):
        raise PackageError(f"archive member is outside package root: {member_name}")
    relative = member_name[len(package_prefix) :]
    if not relative or relative.startswith("/"):
        raise PackageError(f"invalid package member: {member_name}")
    if ".." in PurePosixPath(relative).parts:
        raise PackageError(f"package member escapes package root: {member_name}")
    return relative


def has_forbidden_asset_path(relative: str) -> bool:
    path = Path(relative)
    lowered = relative.lower()
    if path.name.lower() in FORBIDDEN_NAMES:
        return True
    if any(part.lower() in FORBIDDEN_COMPONENTS for part in path.parts):
        return True
    if any(
        part.lower().startswith((".fastembed", "models--"))
        for part in path.parts
    ):
        return True
    if any(lowered.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        return True
    return any(part.endswith(".part") for part in path.parts)


def verify_package(package: Path, expected_version: str) -> dict[str, object]:
    if not VERSION_PATTERN.fullmatch(expected_version):
        raise PackageError(f"invalid expected version: {expected_version}")
    expected_filename = f"{PACKAGE_NAME}-{expected_version}.crate"
    if package.name != expected_filename:
        raise PackageError(
            f"package filename is {package.name!r}, expected {expected_filename!r}"
        )

    package_prefix = f"{PACKAGE_NAME}-{expected_version}/"
    with tarfile.open(package, "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise PackageError("crate archive is empty")
        files: dict[str, bytes] = {}
        for member in members:
            relative = relative_member_name(member.name, package_prefix)
            if has_forbidden_asset_path(relative):
                raise PackageError(f"crate contains mutable/data asset: {member.name}")
            if member.isdir():
                continue
            if not member.isfile():
                raise PackageError(f"crate contains non-regular member: {member.name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise PackageError(f"crate member cannot be read: {member.name}")
            if relative in files:
                raise PackageError(f"crate contains duplicate member: {member.name}")
            files[relative] = extracted.read()

    missing = sorted(REQUIRED_FILES - files.keys())
    if missing:
        raise PackageError(f"crate is missing required files: {', '.join(missing)}")
    unexpected = sorted(
        name
        for name in files
        if name not in REQUIRED_FILES
        and name not in AUTO_GENERATED_FILES
        and not name.startswith("src/")
    )
    if unexpected:
        raise PackageError(f"crate contains non-code release material: {', '.join(unexpected)}")

    cargo_manifest = tomllib.loads(files["Cargo.toml"].decode("utf-8"))
    package_metadata = cargo_manifest.get("package", {})
    if package_metadata.get("name") != PACKAGE_NAME:
        raise PackageError("packaged Cargo.toml has an unexpected package name")
    if package_metadata.get("version") != expected_version:
        raise PackageError("packaged Cargo.toml version does not match package filename")
    lock_text = files["Cargo.lock"].decode("utf-8")
    if f'name = "{PACKAGE_NAME}"\nversion = "{expected_version}"' not in lock_text:
        raise PackageError("packaged Cargo.lock version does not match Cargo.toml")

    digest = sha256_bytes(package.read_bytes())
    return {
        "package": package.name,
        "version": expected_version,
        "archive_sha256": digest,
        "member_count": len(files),
        "members": sorted(files),
        "member_sha256": {name: sha256_bytes(files[name]) for name in sorted(files)},
        "mutable_assets_excluded": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = verify_package(args.package, args.expected_version)
    except (OSError, tarfile.TarError, tomllib.TOMLDecodeError, PackageError) as error:
        raise SystemExit(f"crate package verification failed: {error}") from error
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
