#!/usr/bin/env python3
"""Provision a pinned tldr-pages snapshot and build a matching-bundle-v2.

The source archive is the only network input.  The manifest, parser, model,
and CLI compatibility pins are checked before the offline Rust builder runs.
"""

from __future__ import annotations

import argparse
import gzip
import io
import hashlib
import json
import os
import platform as host_platform
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_REPOSITORY = "https://github.com/tldr-pages/tldr"
UPSTREAM_REVISION = "e7186598dc466e69c2adf5d8f06037d5b186f08d"
UPSTREAM_SOURCE_URL = f"{UPSTREAM_REPOSITORY}/tree/{UPSTREAM_REVISION}"
UPSTREAM_ARCHIVE_URL = (
    f"{UPSTREAM_REPOSITORY}/archive/{UPSTREAM_REVISION}.tar.gz"
)
UPSTREAM_ARCHIVE_SHA256 = (
    "95f4f2604f407d8e148a67be88c9b8957f7ea4da344b6754cbfdb072f94057dd"
)
UPSTREAM_LICENSE_SHA256 = (
    "826498c9793c53709035760c33bd6681e48380d34031320447febe675420ef4d"
)
MANIFEST_PATH = ROOT / "docs/reproducibility/artifacts/tldr-pages-e7186598-manifest.json"
EXPECTED_MANIFEST_SHA256 = "7915b2e6aa0b9006225b8966f97655c7c82507fcf9bfffcc1f314ab41a4fdde2"
PARSER_VERSION = "tldr-subset-v3"
SELECTED_PLATFORMS = ("common", "linux", "osx", "windows")
MODEL_CACHE_FOLDER = "models--Qdrant--all-MiniLM-L6-v2-onnx"
MODEL_REVISION = "5f1b8cd78bc4fb444dd171e59b18f3a3af89a079"
MODEL_RUNTIME = "fastembed-4.8.0"
MODEL_FILES = {
    "config.json": "1b4d8e2a3988377ed8b519a31d8d31025a25f1c5f8606998e8014111438efcd7",
    "model.onnx": "bbd7b466f6d58e646fdc2bd5fd67b2f5e93c0b687011bd4548c420f7bd46f0c5",
    "special_tokens_map.json": "5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a",
    "tokenizer.json": "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0",
    "tokenizer_config.json": "bd2e06a5b20fd1b13ca988bedc8763d332d242381b4fbc98f8fead4524158f79",
}
ONNX_RUNTIME_VERSION = "1.20.0"
ONNX_RUNTIME_ARCHIVE_SHA256 = (
    "2bcfaafa9ff0a3a94f78e3af2f135ffde5bb2d79b08e83a50dbc450b0d20ddae"
)
ONNX_RUNTIME_DYLIB_SHA256 = (
    "d8be733cb8dd097cfe2b21e069a7462b5ff561625141d9c4b98d866f15bfb852"
)
MODEL_NOTICE_PATH = (
    ROOT
    / "docs/reproducibility/artifacts/"
    "model-README-5f1b8cd78bc4fb444dd171e59b18f3a3af89a079.md"
)
MODEL_NOTICE_SHA256 = "2c47a70b94fe29e24841acf0e177949f1c9aa543e450d43af7e872ea81e43501"
CANONICAL_HOST = ("Darwin", "arm64")
EXPECTED_EXCLUSIONS_SHA256 = (
    "e6c349034ffb255a132a1bc94ed412a0b7a9b29a0b31d67eeb906f9590628ac9"
)
TLDR_LICENSE_NAME = "CC-BY-4.0"
TLDR_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
TLDR_ATTRIBUTION = (
    "Copyright © 2014—present the tldr-pages team "
    "(https://github.com/orgs/tldr-pages/people) and contributors "
    "(https://github.com/tldr-pages/tldr/graphs/contributors)."
)
LICENSE_NOTICE_PATHS = (
    "notices/tldr-pages-CC-BY-4.0.txt",
    "notices/all-MiniLM-L6-v2-onnx-README.md",
)
RUNTIME_IDENTITIES = {
    ("Darwin", "arm64"): {
        "archive_name": "onnxruntime-osx-arm64-1.20.0.tgz",
        "library_name": "libonnxruntime.1.20.0.dylib",
        "archive_sha256": ONNX_RUNTIME_ARCHIVE_SHA256,
        "library_sha256": ONNX_RUNTIME_DYLIB_SHA256,
    },
}
DEFAULT_CLI_COMPATIBILITY = "askman=0.4.0"
DEFAULT_PROBES = {
    "common": {
        "query": "copy files",
        "expected_source_path": "pages/common/qcp.md",
        "expected_platform": "common",
    },
    "linux": {
        "query": "restart service",
        "expected_source_path": "pages/linux/rc-service.md",
        "expected_platform": "linux",
    },
    "osx": {
        "query": "say text aloud",
        "expected_source_path": "pages/osx/say.md",
        "expected_platform": "osx",
    },
    "windows": {
        "query": "copy files",
        "expected_source_path": "pages/windows/copy.md",
        "expected_platform": "windows",
    },
}
HYBRID_PROBES = {
    "collision_target_precedence": {
        "platform": "windows",
        "flag": "--windows",
        "query": "copy a file to another location",
        "expected_source_path": "pages/windows/copy.md",
        "expected_platform": "windows",
    },
    "collision_common_fallback": {
        "platform": "osx",
        "flag": None,
        "query": "copy multiple JPEG files",
        "expected_source_path": "pages/common/qcp.md",
        "expected_platform": "common",
    },
    "explicit_linux": {
        "platform": "linux",
        "flag": "--linux",
        "query": "restart service",
        "expected_source_path": "pages/linux/rc-service.md",
        "expected_platform": "linux",
    },
    "explicit_osx": {
        "platform": "osx",
        "flag": "--osx",
        "query": "say text aloud",
        "expected_source_path": "pages/osx/say.md",
        "expected_platform": "osx",
    },
}
EXPECTED_INVENTORY = {
    "source_files": 7415,
    "pages": 7358,
    "examples": 32173,
    "lexical_examples": 31400,
    "pages_by_platform": {
        "common": 4670,
        "linux": 2057,
        "osx": 331,
        "windows": 300,
    },
    "source_files_by_status": {"parsed": 7358, "excluded": 57},
    "dense_index_version": "dense-vec0-v2",
    "dense_retrieval_strategy": "partitioned-knn-v1",
    "dense_partition_key": "platform",
    "dense_partitions": ["common", "linux", "osx", "windows"],
    "dense_rowid_mapping": "example_dense.dense_rowid-v1",
    "dense_row_count": 31400,
}


class ProvisionError(RuntimeError):
    """Raised when a source or output fails the release provisioning contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def exclusions_digest(exclusions: list[dict[str, str]]) -> str:
    canonical = sorted(
        ({"path": item["path"], "reason": item["reason"]} for item in exclusions),
        key=lambda item: item["path"],
    )
    payload = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(payload)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_digest(snapshot: Path, paths: list[str]) -> str:
    """Match tldr_subset's askman-tldr-subset-snapshot-v1 digest exactly."""

    digest = hashlib.sha256()
    digest.update(b"askman-tldr-subset-snapshot-v1\n")
    for relative in sorted(paths):
        data = (snapshot / relative).read_bytes()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(str(len(data)).encode())
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def logical_tree_digest(root: Path) -> str:
    """Hash a directory's logical files, independent of mtimes and inode order."""

    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(str(len(data)).encode())
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def normalize_evidence_path(path: Path, work_dir: Path) -> str:
    resolved = path.resolve()
    run_root = work_dir.resolve()
    try:
        return "${RUN_DIR}/" + resolved.relative_to(run_root).as_posix()
    except ValueError:
        pass
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name


def command_version(command: str, *arguments: str) -> str:
    completed = subprocess.run(
        [command, *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return (completed.stdout or completed.stderr).strip().splitlines()[0]


def _git_bytes(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments], cwd=ROOT, check=True, capture_output=True
    ).stdout


def working_tree_digest() -> str:
    digest = hashlib.sha256()
    paths = _git_bytes("ls-files", "-co", "--exclude-standard", "-z")
    for raw_path in sorted(path for path in paths.split(b"\0") if path):
        relative = raw_path.decode("utf-8")
        path = ROOT / relative
        if path.is_symlink():
            data = os.readlink(path).encode("utf-8")
        else:
            data = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def verify_git_tree(allow_dirty: bool) -> dict[str, object]:
    status = _git_bytes("status", "--porcelain=v1", "--untracked-files=all")
    dirty = bool(status)
    if dirty and not allow_dirty:
        raise ProvisionError(
            "working tree is dirty; production provisioning requires a clean git tree "
            "(use --allow-dirty only for dev evidence)"
        )
    return {
        "status": status,
        "dirty": dirty,
        "allow_dirty": allow_dirty,
        "production_eligible": not dirty and not allow_dirty,
    }


def builder_evidence(
    binary: Path, candidate_binary: Path, git_state: dict[str, object]
) -> dict[str, object]:
    status = git_state["status"]
    assert isinstance(status, bytes)
    diff = _git_bytes("diff", "--binary", "--no-ext-diff", "HEAD", "--")
    return {
        "git_commit": command_version("git", "rev-parse", "HEAD"),
        "git_dirty": git_state["dirty"],
        "allow_dirty": git_state["allow_dirty"],
        "production_eligible": git_state["production_eligible"],
        "git_status_sha256": sha256_bytes(status),
        "git_diff_sha256": sha256_bytes(diff),
        "working_tree_sha256": working_tree_digest(),
        "cargo": command_version("cargo", "--version"),
        "rustc": command_version("rustc", "--version"),
        "python": sys.version.splitlines()[0],
        "builder_binary": {
            "path": "${BUILDER}/" + binary.name,
            "sha256": sha256_file(binary),
        },
        "candidate_binary": {
            "path": "${BUILDER}/" + candidate_binary.name,
            "sha256": sha256_file(candidate_binary),
        },
        "platform": {
            "system": host_platform.system(),
            "release": host_platform.release(),
            "machine": host_platform.machine(),
            "platform": host_platform.platform(),
        },
    }


def _reject_symlink_components(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    try:
        if absolute.is_symlink():
            raise ProvisionError(f"refusing symlink detached output: {absolute}")
    except OSError as error:
        raise ProvisionError(f"failed to inspect detached output path: {absolute}") from error
    return absolute


def emit_detached_manifest(
    internal_manifest: Path, destination: Path, bundle_root: Path
) -> str:
    destination = _reject_symlink_components(destination)
    bundle_root = Path(os.path.realpath(bundle_root))
    if destination == bundle_root or bundle_root in destination.parents:
        raise ProvisionError("detached manifest destination must be outside the bundle")
    resolved_parent = Path(os.path.realpath(destination.parent))
    if resolved_parent == bundle_root or bundle_root in resolved_parent.parents:
        raise ProvisionError("detached manifest parent must be outside the bundle")
    internal_stat = internal_manifest.lstat()
    if not internal_manifest.is_file() or internal_stat.st_mode & 0o170000 == 0o120000:
        raise ProvisionError("bundle manifest must be a regular non-symlink file")
    payload = internal_manifest.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = _reject_symlink_components(destination)
    resolved_parent = Path(os.path.realpath(destination.parent))
    if resolved_parent == bundle_root or bundle_root in resolved_parent.parents:
        raise ProvisionError("detached manifest parent must be outside the bundle")
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    else:
        raise ProvisionError(
            f"refusing to replace existing detached manifest: {destination}"
        )

    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=destination.parent, prefix=f".{destination.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        try:
            os.link(temporary, destination)
        except FileExistsError as error:
            raise ProvisionError(
                f"detached manifest destination appeared during publication: {destination}"
            ) from error
        temporary.unlink()
        temporary = None
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    destination_stat = destination.lstat()
    if destination_stat.st_mode & 0o170000 != 0o100000:
        raise ProvisionError("detached manifest publication produced a non-regular file")
    if destination.read_bytes() != payload:
        raise ProvisionError("detached manifest is not byte-identical to bundle manifest")
    return sha256_bytes(payload)


def _write_deterministic_archive(root: Path, raw: object) -> None:
    """Write stable archive bytes to an already-exclusive file object."""

    with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(path for path in root.rglob("*") if path.is_file()):
                relative = path.relative_to(root).as_posix()
                data = path.read_bytes()
                info = tarfile.TarInfo(relative)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                archive.addfile(info, fileobj=io.BytesIO(data))


def _validate_archive_destination(root: Path, destination: Path) -> Path:
    root = Path(os.path.realpath(root))
    destination = Path(os.path.abspath(destination))
    if destination == root or root in destination.parents:
        raise ProvisionError("bundle archive destination must be outside the bundle")
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    else:
        raise ProvisionError(f"refusing to replace existing bundle archive: {destination}")
    resolved_parent = Path(os.path.realpath(destination.parent))
    if resolved_parent == root or root in resolved_parent.parents:
        raise ProvisionError("bundle archive parent must be outside the bundle")
    return destination


def create_deterministic_archive(root: Path, destination: Path) -> str:
    """Atomically write stable archive bytes without replacing an output."""

    root = Path(os.path.realpath(root))
    destination = _validate_archive_destination(root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = _validate_archive_destination(root, destination)
    temporary: Path | None = None
    try:
        temporary_candidate = destination.parent / f".{destination.name}.part"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(temporary_candidate, flags, 0o600)
        except FileExistsError as error:
            raise ProvisionError(
                f"refusing to reuse existing temporary bundle archive: {temporary_candidate}"
            ) from error
        temporary = temporary_candidate
        with os.fdopen(fd, "wb") as raw:
            _write_deterministic_archive(root, raw)
            raw.flush()
            os.fsync(raw.fileno())
        os.chmod(temporary, 0o644)
        try:
            os.link(temporary, destination)
        except FileExistsError as error:
            raise ProvisionError(
                f"bundle archive destination appeared during publication: {destination}"
            ) from error
        temporary.unlink()
        temporary = None
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        destination_stat = destination.lstat()
        if destination_stat.st_mode & 0o170000 != 0o100000:
            raise ProvisionError("bundle archive publication produced a non-regular file")
        return sha256_file(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProvisionError(f"failed to read manifest {path}: {error}") from error
    if not isinstance(value, dict):
        raise ProvisionError(f"manifest must be a JSON object: {path}")
    return value


def selected_snapshot_paths(snapshot: Path) -> list[str]:
    paths: list[str] = []
    for platform in SELECTED_PLATFORMS:
        root = snapshot / "pages" / platform
        if not root.is_dir():
            raise ProvisionError(f"snapshot is missing pages/{platform}")
        paths.extend(
            path.relative_to(snapshot).as_posix()
            for path in root.rglob("*.md")
            if path.is_file()
        )
    return sorted(paths)


def validate_manifest_snapshot(manifest_path: Path, snapshot: Path) -> dict[str, object]:
    manifest = load_manifest(manifest_path)
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ProvisionError("manifest source metadata is missing")
    if source.get("revision") != UPSTREAM_REVISION:
        raise ProvisionError("manifest source revision is not the pinned upstream revision")
    if source.get("url") != UPSTREAM_SOURCE_URL:
        raise ProvisionError("manifest source URL must be the immutable pinned commit URL")
    manifest_sha256 = sha256_file(manifest_path)
    if manifest_sha256 != EXPECTED_MANIFEST_SHA256:
        raise ProvisionError(
            "manifest content SHA256 drifted from the pinned release input: "
            f"expected={EXPECTED_MANIFEST_SHA256} actual={manifest_sha256}"
        )
    if manifest.get("parser_version") != PARSER_VERSION:
        raise ProvisionError("manifest parser version does not match the builder")
    if manifest.get("language") != "en" or manifest.get("pages_root") != "pages":
        raise ProvisionError("manifest must select English pages below pages/")
    if source.get("attribution") != TLDR_ATTRIBUTION:
        raise ProvisionError("manifest tldr-pages attribution does not match pinned LICENSE.md")
    license_metadata = source.get("license")
    if not isinstance(license_metadata, dict):
        raise ProvisionError("manifest tldr-pages license metadata is missing")
    if license_metadata.get("name") != TLDR_LICENSE_NAME or license_metadata.get("url") != TLDR_LICENSE_URL:
        raise ProvisionError("manifest tldr-pages license must be CC-BY-4.0")
    provisioning = manifest.get("provisioning")
    if not isinstance(provisioning, dict):
        raise ProvisionError("manifest provisioning pins are missing")
    if provisioning.get("archive_sha256") != UPSTREAM_ARCHIVE_SHA256:
        raise ProvisionError("manifest archive SHA256 pin is incompatible")
    if provisioning.get("license_sha256") != UPSTREAM_LICENSE_SHA256:
        raise ProvisionError("manifest LICENSE.md SHA256 pin is incompatible")

    files = manifest.get("files")
    exclusions = manifest.get("exclusions", [])
    if not isinstance(files, list) or not all(isinstance(path, str) for path in files):
        raise ProvisionError("manifest files must be a list of paths")
    if not isinstance(exclusions, list) or not all(isinstance(item, dict) for item in exclusions):
        raise ProvisionError("manifest exclusions must be a list of objects")
    declared = [str(path) for path in files]
    discovered = selected_snapshot_paths(snapshot)
    if declared != sorted(declared) or len(set(declared)) != len(declared):
        raise ProvisionError("manifest files must be sorted and unique")
    if declared != discovered:
        missing = sorted(set(discovered) - set(declared))
        unexpected = sorted(set(declared) - set(discovered))
        raise ProvisionError(
            "manifest does not exhaustively account for selected .md files; "
            f"missing={missing[:5]} unexpected={unexpected[:5]}"
        )

    exclusion_paths: set[str] = set()
    for item in exclusions:
        path = item.get("path")
        reason = item.get("reason")
        if not isinstance(path, str) or not isinstance(reason, str) or not reason.strip():
            raise ProvisionError("every exclusion needs a path and non-empty reason")
        if path in exclusion_paths or path not in set(declared):
            raise ProvisionError(f"invalid or duplicate exclusion path: {path}")
        exclusion_paths.add(path)
    actual_exclusions_digest = exclusions_digest(exclusions)
    if actual_exclusions_digest != EXPECTED_EXCLUSIONS_SHA256:
        raise ProvisionError(
            "manifest exclusion set/reasons drifted from the frozen pin: "
            f"expected={EXPECTED_EXCLUSIONS_SHA256} actual={actual_exclusions_digest}"
        )
    if provisioning.get("exclusions_sha256") != actual_exclusions_digest:
        raise ProvisionError("manifest exclusion digest does not match its exclusions")
    expected_digest = source.get("digest")
    actual_digest = source_digest(snapshot, declared)
    if expected_digest != actual_digest:
        raise ProvisionError(
            f"source snapshot digest mismatch: expected={expected_digest} actual={actual_digest}"
        )

    license_path = snapshot / "LICENSE.md"
    if not license_path.is_file() or sha256_file(license_path) != UPSTREAM_LICENSE_SHA256:
        raise ProvisionError("pinned tldr-pages LICENSE.md failed SHA256 verification")
    license_text = license_path.read_text(encoding="utf-8")
    for required_text in (
        "Creative Commons Attribution 4.0 International License",
        "https://github.com/orgs/tldr-pages/people",
        "https://github.com/tldr-pages/tldr/graphs/contributors",
    ):
        if required_text not in license_text:
            raise ProvisionError(f"pinned tldr-pages LICENSE.md is missing attribution text: {required_text}")

    return {
        "manifest": manifest,
        "files": declared,
        "exclusions": exclusions,
        "source_digest": actual_digest,
        "file_count": len(declared),
        "excluded_count": len(exclusion_paths),
        "parsed_count": len(declared) - len(exclusion_paths),
        "exclusions_sha256": actual_exclusions_digest,
    }


def download_verified(url: str, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        actual = sha256_file(destination)
        if actual != expected_sha256:
            raise ProvisionError(
                f"existing archive has wrong SHA256: expected={expected_sha256} actual={actual}"
            )
        return

    with NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        request = Request(url, headers={"User-Agent": "askman-release-provisioner"})
        with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        actual = sha256_file(temporary)
        if actual != expected_sha256:
            raise ProvisionError(
                f"downloaded archive has wrong SHA256: expected={expected_sha256} actual={actual}"
            )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def archive_root(archive: Path) -> str:
    with tarfile.open(archive, "r:gz") as stream:
        roots = {
            member.name.split("/", 1)[0]
            for member in stream.getmembers()
            if member.name
        }
    if len(roots) != 1:
        raise ProvisionError(f"upstream archive has unexpected root entries: {sorted(roots)}")
    return roots.pop()


def extract_archive(archive: Path, work_dir: Path) -> Path:
    snapshot = work_dir / "snapshot"
    if snapshot.is_dir():
        return snapshot
    extraction = work_dir / ".tldr-extract"
    if extraction.exists():
        raise ProvisionError(f"refusing to reuse incomplete extraction: {extraction}")
    extraction.mkdir(parents=True)
    root_name = archive_root(archive)
    root = extraction / root_name
    try:
        with tarfile.open(archive, "r:gz") as stream:
            for member in stream.getmembers():
                target = (extraction / member.name).resolve()
                if not target.is_relative_to(extraction.resolve()):
                    raise ProvisionError(f"archive member escapes extraction root: {member.name}")
                if member.islnk():
                    raise ProvisionError(f"archive contains unsupported hard link: {member.name}")
                if not (member.isdir() or member.isfile() or member.issym()):
                    raise ProvisionError(f"archive contains unsupported member: {member.name}")
                if member.issym():
                    link_target = (
                        extraction / Path(member.name).parent / member.linkname
                    ).resolve()
                    if not link_target.is_relative_to(extraction.resolve()):
                        raise ProvisionError(
                            f"archive symlink escapes extraction root: {member.name}"
                        )
            stream.extractall(extraction)
        if not root.is_dir():
            raise ProvisionError("upstream archive root directory is missing")
        root.rename(snapshot)
        extraction.rmdir()
    except Exception:
        shutil.rmtree(extraction, ignore_errors=True)
        raise
    return snapshot


def model_cache_files(model_cache: Path) -> dict[str, dict[str, object]]:
    root = model_cache / MODEL_CACHE_FOLDER
    reference = root / "refs" / "main"
    if not reference.is_file() or reference.read_text(encoding="ascii").strip() != MODEL_REVISION:
        raise ProvisionError(f"model cache reference is not pinned to {MODEL_REVISION}")
    assets: dict[str, dict[str, object]] = {}
    for name, expected in MODEL_FILES.items():
        path = root / "snapshots" / MODEL_REVISION / name
        if not path.is_file() or sha256_file(path) != expected:
            raise ProvisionError(f"model cache asset failed SHA256 verification: {name}")
        assets[name] = {"sha256": expected, "size_bytes": path.stat().st_size}
    return assets


def verify_model_license_notice() -> dict[str, object]:
    if not MODEL_NOTICE_PATH.is_file():
        raise ProvisionError(f"pinned model README/license notice is missing: {MODEL_NOTICE_PATH}")
    actual_sha256 = sha256_file(MODEL_NOTICE_PATH)
    if actual_sha256 != MODEL_NOTICE_SHA256:
        raise ProvisionError(
            "pinned model README/license notice failed SHA256 verification: "
            f"expected={MODEL_NOTICE_SHA256} actual={actual_sha256}"
        )
    text = MODEL_NOTICE_PATH.read_text(encoding="utf-8")
    if "license: apache-2.0" not in text:
        raise ProvisionError("pinned model README/license notice does not declare Apache-2.0")
    return {
        "path": MODEL_NOTICE_PATH,
        "sha256": actual_sha256,
        "size_bytes": MODEL_NOTICE_PATH.stat().st_size,
        "license": "Apache-2.0",
        "source_url": (
            "https://huggingface.co/Qdrant/all-MiniLM-L6-v2-onnx/"
            f"resolve/{MODEL_REVISION}/README.md"
        ),
    }


def tool_command(binary: Path | None, cargo: str, arguments: list[str]) -> list[str]:
    if binary is not None:
        return [str(binary), *arguments]
    return [cargo, "run", "--locked", "--offline", "--features", "dev", "--bin", "tldr_subset", "--", *arguments]


def run_tool(
    binary: Path | None,
    cargo: str,
    arguments: list[str],
    environment: dict[str, str],
    *,
    allow_published_bundle_after_abort: bool = False,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        tool_command(binary, cargo, arguments),
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        output = f"{completed.stdout}\n{completed.stderr}"
        if not (
            allow_published_bundle_after_abort
            and "built matching bundle" in output
        ):
            raise ProvisionError(
                f"tldr_subset {' '.join(arguments[:1])} failed ({completed.returncode}):\n{output[-4000:]}"
            )
    return completed


def database_inventory(database: Path) -> dict[str, object]:
    connection = sqlite3.connect(database)
    try:
        def metadata(key: str) -> str:
            return str(
                connection.execute(
                    "SELECT value FROM artifact_metadata WHERE key = ?", (key,)
                ).fetchone()[0]
            )

        def count(table: str) -> int:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        pages_by_platform = {
            platform: int(
                connection.execute(
                    "SELECT COUNT(*) FROM pages WHERE platform = ?", (platform,)
                ).fetchone()[0]
            )
            for platform in SELECTED_PLATFORMS
        }
        source_status = {
            status: int(
                connection.execute(
                    "SELECT COUNT(*) FROM source_files WHERE status = ?", (status,)
                ).fetchone()[0]
            )
            for status in ("parsed", "excluded")
        }
        return {
            "source_files": count("source_files"),
            "pages": count("pages"),
            "examples": count("examples"),
            "lexical_examples": int(connection.execute("SELECT COUNT(*) FROM example_lexical").fetchone()[0]),
            "pages_by_platform": pages_by_platform,
            "source_files_by_status": source_status,
            "source_digest": connection.execute(
                "SELECT value FROM artifact_metadata WHERE key = 'source_digest'"
            ).fetchone()[0],
            "dense_index_version": metadata("dense_index_version"),
            "dense_retrieval_strategy": metadata("dense_retrieval_strategy"),
            "dense_partition_key": metadata("dense_partition_key"),
            "dense_partitions": json.loads(metadata("dense_partitions")),
            "dense_rowid_mapping": metadata("dense_rowid_mapping"),
            "dense_row_count": int(metadata("dense_row_count")),
        }
    finally:
        connection.close()


def verify_runtime(
    runtime_lib: Path | None,
    runtime_archive: Path | None,
    binary: Path | None,
    environment: dict[str, str],
    candidate_binary: Path | None = None,
) -> dict[str, object]:
    if (
        runtime_lib is None
        or runtime_archive is None
        or binary is None
        or candidate_binary is None
    ):
        raise ProvisionError(
            "--tldr-subset, --askman-candidate, --runtime-lib, and "
            "--runtime-archive are required; host ONNX Runtime linkage is not advisory"
        )
    system = host_platform.system()
    machine = host_platform.machine()
    if (system, machine) != CANONICAL_HOST:
        raise ProvisionError(
            "production bundle builds are pinned to the canonical host "
            f"{CANONICAL_HOST[0]}/{CANONICAL_HOST[1]}; observed {system}/{machine}"
        )
    identity = RUNTIME_IDENTITIES.get((system, machine))
    if identity is None:
        raise ProvisionError(
            f"no pinned ONNX Runtime 1.20.0 identity for host platform {system}/{machine}"
        )
    runtime_lib = runtime_lib.resolve()
    runtime_archive = runtime_archive.resolve()
    binary = binary.resolve()
    candidate_binary = candidate_binary.resolve()
    if not binary.is_file():
        raise ProvisionError(f"tldr_subset binary is missing: {binary}")
    if not candidate_binary.is_file():
        raise ProvisionError(f"askman_candidate binary is missing: {candidate_binary}")
    if not runtime_lib.is_dir():
        raise ProvisionError(f"ONNX Runtime library directory is missing: {runtime_lib}")
    if not runtime_archive.is_file():
        raise ProvisionError(f"ONNX Runtime archive is missing: {runtime_archive}")
    if runtime_archive.name != identity["archive_name"]:
        raise ProvisionError(
            f"ONNX Runtime archive name is incompatible: expected={identity['archive_name']} actual={runtime_archive.name}"
        )
    archive_sha256 = sha256_file(runtime_archive)
    if archive_sha256 != identity["archive_sha256"]:
        raise ProvisionError(
            "provisioned ONNX Runtime archive failed SHA256 verification: "
            f"expected={identity['archive_sha256']} actual={archive_sha256}"
        )
    dylib = runtime_lib / identity["library_name"]
    if not dylib.is_file():
        raise ProvisionError(f"ONNX Runtime library is missing: {dylib}")
    library_sha256 = sha256_file(dylib)
    if library_sha256 != identity["library_sha256"]:
        raise ProvisionError(
            "provisioned ONNX Runtime library failed SHA256 verification: "
            f"expected={identity['library_sha256']} actual={library_sha256}"
        )

    environment["DYLD_LIBRARY_PATH"] = str(runtime_lib)
    environment["ORT_PREFER_DYNAMIC_LINK"] = "1"
    environment["LIBONNXRUNTIME_NO_PKG_CONFIG"] = "1"
    environment["ORT_LIB_LOCATION"] = str(runtime_lib.parent)
    info: dict[str, object] = {
        "version": ONNX_RUNTIME_VERSION,
        "verified": True,
        "platform": {"system": system, "machine": machine},
        "archive_name": runtime_archive.name,
        "archive_sha256": archive_sha256,
        "library_name": identity["library_name"],
        "library_sha256": library_sha256,
        "library_directory": str(runtime_lib),
    }
    otool = shutil.which("otool")
    if otool is None:
        raise ProvisionError("otool is required to verify host ONNX Runtime linkage")

    expected_architecture = {
        "arm64": "ARM64",
        "x86_64": "X86_64",
    }.get(machine)
    if expected_architecture is None:
        raise ProvisionError(f"unsupported canonical binary architecture: {machine}")

    def verify_binary_linkage(label: str, path: Path) -> dict[str, object]:
        header = subprocess.run(
            [otool, "-hv", str(path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if expected_architecture not in header:
            raise ProvisionError(
                f"{label} is not built for {machine}: expected {expected_architecture}"
            )
        linkage = subprocess.run(
            [otool, "-L", str(path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        linked_library = f"@rpath/{identity['library_name']}"
        if linked_library not in linkage:
            raise ProvisionError(
                f"{label} is not linked to exact {linked_library} from the pinned runtime"
            )
        return {
            "binary_path": str(path),
            "architecture": machine,
            "architecture_verified": True,
            "binary_linkage": next(
                line.strip() for line in linkage.splitlines() if linked_library in line
            ),
            "linked_library": linked_library,
            "linkage_verified_library_path": str(dylib),
            "linkage_verified_library_sha256": library_sha256,
        }

    binaries = {
        "tldr_subset": verify_binary_linkage("tldr_subset", binary),
        "askman_candidate": verify_binary_linkage("askman_candidate", candidate_binary),
    }
    info["binary_path"] = str(binary)
    info["binary_linkage"] = binaries["tldr_subset"]["binary_linkage"]
    info["candidate_binary_path"] = str(candidate_binary)
    info["candidate_binary_linkage"] = binaries["askman_candidate"]["binary_linkage"]
    info["linkage_verified_library_path"] = str(dylib)
    info["linkage_verified_library_sha256"] = library_sha256
    info["binaries"] = binaries
    return info


def query_probe(
    binary: Path | None,
    cargo: str,
    database: Path,
    platform: str,
    probe: dict[str, str],
    environment: dict[str, str],
) -> dict[str, object]:
    query = probe["query"]
    completed = run_tool(
        binary,
        cargo,
        [
            "query",
            "--artifact",
            str(database),
            "--platform",
            platform,
            "--query",
            query,
            "--limit",
            "3",
        ],
        environment,
    )
    try:
        results = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ProvisionError(f"query probe did not return JSON for {platform}: {error}") from error
    if not isinstance(results, list) or not results:
        raise ProvisionError(f"query probe returned no results for {platform}: {query}")
    if any(result.get("platform") not in (platform, "common") for result in results):
        raise ProvisionError(f"query probe returned a non-selected platform for {platform}")
    top_result = results[0]
    expected_source_path = probe["expected_source_path"]
    expected_platform = probe["expected_platform"]
    if top_result.get("source_path") != expected_source_path:
        raise ProvisionError(
            f"query probe top source mismatch for {platform}: "
            f"expected={expected_source_path} actual={top_result.get('source_path')}"
        )
    if top_result.get("platform") != expected_platform:
        raise ProvisionError(
            f"query probe top platform mismatch for {platform}: "
            f"expected={expected_platform} actual={top_result.get('platform')}"
        )
    return {
        "query": query,
        "expected_source_path": expected_source_path,
        "expected_platform": expected_platform,
        "result_count": len(results),
        "top_source_path": top_result.get("source_path"),
        "top_platform": top_result.get("platform"),
        "top_example_id": top_result.get("example_id"),
    }


def hybrid_probe(
    candidate_binary: Path,
    bundle: Path,
    probe: dict[str, str | None],
    environment: dict[str, str],
) -> dict[str, object]:
    command = [str(candidate_binary), "--bundle", str(bundle)]
    if probe["flag"]:
        command.append(probe["flag"])
    command.extend(["--json", *str(probe["query"]).split()])
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        results = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ProvisionError(
            f"hybrid query probe did not return JSON for {probe['platform']}: {error}"
        ) from error
    if not isinstance(results, list) or not results:
        raise ProvisionError(f"hybrid query probe returned no results: {probe['query']}")
    if not any(result.get("dense_distance") is not None for result in results):
        raise ProvisionError(
            f"hybrid query probe did not exercise dense retrieval: {probe['query']}"
        )
    top_result = results[0]
    if top_result.get("source_path") != probe["expected_source_path"]:
        raise ProvisionError(
            "hybrid probe top source mismatch for "
            f"{probe['platform']}: expected={probe['expected_source_path']} "
            f"actual={top_result.get('source_path')}"
        )
    if top_result.get("platform") != probe["expected_platform"]:
        raise ProvisionError(
            "hybrid probe top platform mismatch for "
            f"{probe['platform']}: expected={probe['expected_platform']} "
            f"actual={top_result.get('platform')}"
        )
    return {
        "query": probe["query"],
        "platform": probe["platform"],
        "explicit_flag": probe["flag"],
        "expected_source_path": probe["expected_source_path"],
        "expected_platform": probe["expected_platform"],
        "result_count": len(results),
        "top_source_path": top_result.get("source_path"),
        "top_platform": top_result.get("platform"),
        "dense_result_count": sum(
            result.get("dense_distance") is not None for result in results
        ),
    }


def build_provision(
    work_dir: Path,
    manifest_path: Path,
    model_cache: Path,
    output: Path,
    report_path: Path,
    binary: Path | None,
    candidate_binary: Path | None,
    cargo: str,
    cli_compatibility: str,
    runtime_lib: Path | None,
    runtime_archive: Path | None,
    check_rebuild: bool,
    archive_output: Path | None,
    detached_manifest_output: Path | None,
    allow_dirty: bool,
) -> dict[str, object]:
    if binary is None or candidate_binary is None:
        raise ProvisionError(
            "--tldr-subset and --askman-candidate are required for shipping-path probes"
        )
    candidate_binary = candidate_binary.resolve()
    if not candidate_binary.is_file():
        raise ProvisionError(f"askman_candidate binary is missing: {candidate_binary}")
    git_state = verify_git_tree(allow_dirty)
    work_dir.mkdir(parents=True, exist_ok=True)
    work_dir = work_dir.resolve()
    archive = work_dir / f"tldr-pages-{UPSTREAM_REVISION}.tar.gz"
    download_verified(UPSTREAM_ARCHIVE_URL, archive, UPSTREAM_ARCHIVE_SHA256)
    snapshot = extract_archive(archive, work_dir)
    manifest_info = validate_manifest_snapshot(manifest_path, snapshot)
    model_assets = model_cache_files(model_cache)
    model_notice = verify_model_license_notice()

    environment = os.environ.copy()
    runtime_info = verify_runtime(
        runtime_lib,
        runtime_archive,
        binary,
        environment,
        candidate_binary,
    )
    runtime_info["library_directory"] = "${ORT_ROOT}/" + runtime_lib.name
    runtime_info["library_path"] = (
        "${ORT_ROOT}/" + runtime_lib.name + "/" + runtime_info["library_name"]
    )
    runtime_info["linkage_verified_library_path"] = runtime_info["library_path"]
    runtime_info["binary_path"] = "${BUILDER}/" + binary.name
    runtime_info["archive_path"] = "${RUN_DIR}/" + runtime_archive.name
    runtime_info["candidate_binary_path"] = "${BUILDER}/" + candidate_binary.name
    for binary_info in runtime_info["binaries"].values():
        binary_info["binary_path"] = "${BUILDER}/" + Path(binary_info["binary_path"]).name
        binary_info["linkage_verified_library_path"] = runtime_info["library_path"]

    output = output.resolve()
    if output.exists():
        raise ProvisionError(f"refusing to replace existing bundle output: {output}")
    archive_output = (archive_output or output.parent / "matching-bundle.tar.gz").resolve()
    detached_manifest_output = Path(
        os.path.abspath(
            detached_manifest_output
            or output.parent / "matching-bundle-manifest.json"
        )
    )
    detached_absolute = _reject_symlink_components(detached_manifest_output)
    output_absolute = Path(os.path.abspath(output))
    if detached_absolute == output_absolute or output_absolute in detached_absolute.parents:
        raise ProvisionError("detached manifest destination must be outside the bundle")
    run_tool(
        binary,
        cargo,
        [
            "bundle-build",
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot),
            "--model-cache",
            str(model_cache),
            "--output",
            str(output),
            "--cli-compatibility",
            cli_compatibility,
        ],
        environment,
        allow_published_bundle_after_abort=True,
    )
    validated = run_tool(binary, cargo, ["bundle-validate", "--bundle", str(output)], environment)
    database = output / "matching.db"
    internal_manifest_path = output / "manifest.json"
    internal_manifest_bytes = internal_manifest_path.read_bytes()
    manifest = json.loads(internal_manifest_bytes)
    detached_manifest_sha256 = emit_detached_manifest(
        internal_manifest_path, detached_manifest_output, output
    )
    inventory = database_inventory(database)
    expected_inventory = dict(EXPECTED_INVENTORY)
    expected_inventory["source_digest"] = manifest_info["source_digest"]
    for key, expected in expected_inventory.items():
        if inventory[key] != expected:
            raise ProvisionError(f"bundle inventory mismatch for {key}: expected={expected} got={inventory[key]}")

    probes = {
        platform: query_probe(binary, cargo, database, platform, probe, environment)
        for platform, probe in DEFAULT_PROBES.items()
    }
    hybrid_probes = {
        name: hybrid_probe(candidate_binary, output, probe, environment)
        for name, probe in HYBRID_PROBES.items()
    }
    tree_digest = logical_tree_digest(output)
    archive_digest = create_deterministic_archive(output, archive_output)
    notice_metadata = [
        {
            "path": relative,
            "size_bytes": (output / relative).stat().st_size,
            "sha256": sha256_file(output / relative),
        }
        for relative in LICENSE_NOTICE_PATHS
    ]
    bundled_model_notice = output / LICENSE_NOTICE_PATHS[1]
    if bundled_model_notice.read_bytes() != MODEL_NOTICE_PATH.read_bytes():
        raise ProvisionError("bundle model license notice is not byte-identical to pinned model README")
    rebuild: dict[str, object] = {"checked": False}
    if check_rebuild:
        rebuild_output = output.with_name(f"{output.name}-rebuild")
        run_tool(
            binary,
            cargo,
            [
                "bundle-build",
                "--manifest",
                str(manifest_path),
                "--snapshot",
                str(snapshot),
                "--model-cache",
                str(model_cache),
                "--output",
                str(rebuild_output),
                "--cli-compatibility",
                cli_compatibility,
            ],
            environment,
            allow_published_bundle_after_abort=True,
        )
        run_tool(binary, cargo, ["bundle-validate", "--bundle", str(rebuild_output)], environment)
        rebuild_digest = logical_tree_digest(rebuild_output)
        if rebuild_digest != tree_digest:
            raise ProvisionError(
                f"logical bundle rebuild differs: first={tree_digest} rebuild={rebuild_digest}"
            )
        rebuild_manifest_bytes = (rebuild_output / "manifest.json").read_bytes()
        if rebuild_manifest_bytes != internal_manifest_bytes:
            raise ProvisionError("bundle manifest rebuild is not byte-identical")
        rebuild_archive = rebuild_output.with_suffix(".tar.gz")
        rebuild_archive_digest = create_deterministic_archive(
            rebuild_output, rebuild_archive
        )
        if rebuild_archive_digest != archive_digest:
            raise ProvisionError(
                "deterministic bundle archive rebuild differs: "
                f"first={archive_digest} rebuild={rebuild_archive_digest}"
            )
        rebuild = {
            "checked": True,
            "tree_sha256": rebuild_digest,
            "path": normalize_evidence_path(rebuild_output, work_dir),
            "manifest_sha256": sha256_bytes(rebuild_manifest_bytes),
            "archive_path": normalize_evidence_path(rebuild_archive, work_dir),
            "archive_sha256": rebuild_archive_digest,
            "archive_matches": True,
        }

    report = {
        "schema_version": 1,
        "builder": builder_evidence(binary, candidate_binary, git_state),
        "source": {
            "repository": UPSTREAM_SOURCE_URL,
            "revision": UPSTREAM_REVISION,
            "archive_url": UPSTREAM_ARCHIVE_URL,
            "archive_sha256": UPSTREAM_ARCHIVE_SHA256,
            "archive_path": normalize_evidence_path(archive, work_dir),
            "license_path": "LICENSE.md",
            "license_sha256": UPSTREAM_LICENSE_SHA256,
            "manifest_path": normalize_evidence_path(manifest_path, work_dir),
            "manifest_sha256": sha256_file(manifest_path),
            "snapshot_digest": manifest_info["source_digest"],
            "attribution": TLDR_ATTRIBUTION,
            "license": {"name": TLDR_LICENSE_NAME, "url": TLDR_LICENSE_URL},
            "exclusions_sha256": manifest_info["exclusions_sha256"],
        },
        "selection": {
            "language": "en",
            "platforms": list(SELECTED_PLATFORMS),
            "file_count": manifest_info["file_count"],
            "parsed_count": manifest_info["parsed_count"],
            "excluded_count": manifest_info["excluded_count"],
            "exclusions_sha256": manifest_info["exclusions_sha256"],
        },
        "model": {
            "id": "Qdrant/all-MiniLM-L6-v2-onnx",
            "revision": MODEL_REVISION,
            "runtime": MODEL_RUNTIME,
            "onnx_runtime": runtime_info,
            "assets": model_assets,
            "license_notice": {
                "path": normalize_evidence_path(model_notice["path"], work_dir),
                "sha256": model_notice["sha256"],
                "size_bytes": model_notice["size_bytes"],
                "license": model_notice["license"],
                "source_url": model_notice["source_url"],
            },
        },
        "bundle": {
            "path": normalize_evidence_path(output, work_dir),
            "bundle_id": manifest["bundle_id"],
            "manifest_sha256": sha256_file(output / "manifest.json"),
            "detached_manifest_path": normalize_evidence_path(
                detached_manifest_output, work_dir
            ),
            "detached_manifest_sha256": detached_manifest_sha256,
            "detached_manifest_byte_identical": detached_manifest_output.read_bytes()
            == internal_manifest_bytes,
            "license_notices": notice_metadata,
            "tree_sha256": tree_digest,
            "matching_db_sha256": sha256_file(database),
            "matching_db_size_bytes": database.stat().st_size,
            "cli_compatibility": manifest["cli_compatibility"],
            "inventory": inventory,
            "probes": probes,
            "hybrid_probes": hybrid_probes,
            "validation_output": validated.stdout.strip(),
            "archive_path": normalize_evidence_path(archive_output, work_dir),
            "archive_sha256": archive_digest,
        },
        "rebuild": rebuild,
    }
    write_json(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--tldr-subset", type=Path, required=True)
    parser.add_argument("--askman-candidate", type=Path, required=True)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--cli-compatibility", default=DEFAULT_CLI_COMPATIBILITY)
    parser.add_argument("--runtime-lib", type=Path, required=True)
    parser.add_argument("--runtime-archive", type=Path, required=True)
    parser.add_argument(
        "--archive-output",
        type=Path,
        help="optional deterministic matching-bundle.tar.gz output",
    )
    parser.add_argument(
        "--detached-manifest-output",
        type=Path,
        help="optional detached matching-bundle-manifest.json output",
    )
    parser.add_argument("--check-rebuild", action="store_true")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="dev-only: permit a dirty git tree and mark evidence production-ineligible",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = args.report or args.output.with_suffix(".provision.json")
    try:
        result = build_provision(
            args.work_dir,
            args.manifest,
            args.model_cache,
            args.output,
            report,
            args.tldr_subset,
            args.askman_candidate,
            args.cargo,
            args.cli_compatibility,
            args.runtime_lib,
            args.runtime_archive,
            args.check_rebuild,
            args.archive_output,
            args.detached_manifest_output,
            args.allow_dirty,
        )
    except (OSError, ProvisionError, subprocess.SubprocessError) as error:
        print(f"provisioning failed: {error}", file=sys.stderr)
        return 1
    print(
        f"built {result['bundle']['bundle_id']} with "
        f"{result['selection']['parsed_count']} pages and "
        f"{result['bundle']['inventory']['examples']} examples"
    )
    print(f"report={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
