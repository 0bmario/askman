#!/usr/bin/env python3
"""Smoke-test one extracted release asset against a staged production bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci_offline import (
    TARGET_QUERIES,
    parse_shipping_json,
    require_runtime_identity,
    runtime_metadata,
    sha256_file,
    write_json,
)


class AssetVerificationError(RuntimeError):
    pass


# A release verification job may inherit the build job's cache-backed loader
# variables.  Leaving any of them in place would let ldd/otool or the shipping
# process resolve a different ONNX Runtime than the one beside the extracted
# binary.  The local ORT variables are restored below, pointing only at the
# extracted archive.
ARCHIVE_RUNTIME_ENVIRONMENT = (
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "LD_AUDIT",
    "DYLD_LIBRARY_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_FALLBACK_FRAMEWORK_PATH",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_ROOT_PATH",
    "ORT_LIBRARY_PATH",
    "ORT_LIB_LOCATION",
    "ORT_ROOT",
    "ORT_VERSION",
    "XDG_CACHE_HOME",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "HOME",
    "USERPROFILE",
)


def archive_runtime_environment(extracted: Path, expected_version: str | None) -> dict[str, str]:
    """Return an environment where the extracted archive is the only ORT root."""

    environment = os.environ.copy()
    for variable in ARCHIVE_RUNTIME_ENVIRONMENT:
        environment.pop(variable, None)
    isolated_home = extracted / ".runtime-home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "ORT_LIB_LOCATION": str(extracted),
            "ORT_LIBRARY_PATH": str(extracted),
            "ORT_ROOT": str(extracted),
            "HOME": str(isolated_home),
            "USERPROFILE": str(isolated_home),
        }
    )
    if expected_version:
        environment["ORT_EXPECTED_VERSION"] = expected_version
    # Windows resolves a DLL beside the executable first, but an inherited
    # cache/runtime directory in PATH would still make the evidence ambiguous.
    # Keep ordinary tool/system entries (dumpbin/objdump may be needed for
    # linkage capture) while dropping known ORT/cache locations and prepending
    # the exact archive directory.
    path_entries = []
    for entry in environment.get("PATH", "").split(os.pathsep):
        lowered = entry.lower()
        if entry and not any(
            token in lowered
            for token in ("onnxruntime", "ort.pyke.io", "\\ort", "/ort", "\\cache", "/cache")
        ):
            path_entries.append(entry)
    environment["PATH"] = os.pathsep.join([str(extracted), *path_entries])
    return environment


def _path_inside(path: Path, root: Path, label: str) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise AssetVerificationError(f"{label} is outside the extracted release archive: {path}")
    return resolved_path


def _archive_member_path(extracted: Path, member: object, label: str) -> Path:
    if not isinstance(member, str) or not member or Path(member).is_absolute():
        raise AssetVerificationError(f"{label} is not a relative archive member")
    return _path_inside(extracted / member, extracted, label)


def capture_archive_runtime_identity(
    extracted: Path,
    binary: Path,
    expected_version: str | None,
    manifest: dict[str, object],
) -> dict[str, object]:
    """Re-resolve the exact extracted binary/runtime with cache variables removed."""

    environment = archive_runtime_environment(extracted, expected_version)
    previous = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(environment)
        evidence = runtime_metadata({"shipping": binary})
        require_runtime_identity(evidence, expected_version=expected_version)
    finally:
        os.environ.clear()
        os.environ.update(previous)

    runtime = evidence.get("onnx_runtime")
    shipping = evidence.get("binaries", {}).get("shipping") if isinstance(evidence.get("binaries"), dict) else None
    if not isinstance(runtime, dict) or not isinstance(shipping, dict):
        raise AssetVerificationError("archive runtime identity is incomplete")
    runtime_path = runtime.get("library_path")
    binary_path = shipping.get("path")
    if not isinstance(runtime_path, str) or not isinstance(binary_path, str):
        raise AssetVerificationError("archive runtime identity has no resolved paths")
    _path_inside(Path(runtime_path), extracted, "linked ONNX Runtime path")
    _path_inside(Path(binary_path), extracted, "shipping binary path")

    archive_runtime = manifest.get("onnx_runtime")
    archive_binary = manifest.get("binary")
    if not isinstance(archive_runtime, dict) or not isinstance(archive_binary, dict):
        raise AssetVerificationError("release archive manifest has incomplete identities")
    if Path(runtime_path).name != str(archive_runtime.get("library")):
        raise AssetVerificationError("linked ONNX Runtime path is not the archive runtime")
    if Path(binary_path).name != str(archive_binary.get("path")):
        raise AssetVerificationError("linked shipping binary path is not the archive binary")
    if runtime.get("library_sha256") != archive_runtime.get("sha256"):
        raise AssetVerificationError("linked ONNX Runtime SHA differs from archive manifest")
    if shipping.get("sha256") != archive_binary.get("sha256"):
        raise AssetVerificationError("linked shipping binary SHA differs from archive manifest")
    return evidence


def storage_name(bundle_id: str) -> str:
    return "".join(
        character
        if character.isascii() and (character.isalnum() or character in ".-_")
        else f"%{ord(character):02x}"
        for character in bundle_id
    )


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as stream:
        root = destination.resolve()
        for member in stream.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root):
                raise AssetVerificationError(f"archive entry escapes extraction root: {member.name}")
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise AssetVerificationError(f"release archive contains an unsafe entry: {member.name}")
        stream.extractall(destination)


def validate_existing_extraction(archive: Path, destination: Path) -> None:
    """Validate a caller-owned extraction without making a second copy."""

    if not destination.is_dir():
        raise AssetVerificationError(f"pre-extracted release directory is missing: {destination}")
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise AssetVerificationError(f"archive entry escapes extraction root: {member.name}")
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise AssetVerificationError(f"release archive contains an unsafe entry: {member.name}")
            if member.isfile():
                if not target.is_file():
                    raise AssetVerificationError(f"pre-extracted archive member is missing: {member.name}")
                source = stream.extractfile(member)
                if source is None or source.read() != target.read_bytes():
                    raise AssetVerificationError(f"pre-extracted archive member differs: {member.name}")


def run_binary(
    binary: Path,
    arguments: list[str],
    data_dir: Path,
    report_dir: Path,
    label: str,
    runtime_environment: dict[str, str] | None = None,
) -> tuple[int, str]:
    environment = (runtime_environment or os.environ).copy()
    environment.update(
        {
            "ASKMAN_DATA_DIR": str(data_dir),
            "ASKMAN_RELEASE_BASE_URL": "http://127.0.0.1:9/blocked-release",
            "CLICOLOR_FORCE": "0",
            "NO_COLOR": "1",
        }
    )
    completed = subprocess.run(
        [str(binary), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (report_dir / f"{label}.log").write_text(completed.stdout or "", encoding="utf-8")
    return completed.returncode, completed.stdout or ""


def stage_bundle(
    bundle_archive: Path,
    bundle_manifest: Path,
    data_dir: Path,
    bundle_report: Path | None,
) -> dict[str, object]:
    manifest_bytes = bundle_manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("bundle_id"), str):
        raise AssetVerificationError("production bundle manifest is invalid")
    if bundle_report:
        report = json.loads(bundle_report.read_text(encoding="utf-8"))
        builder = report.get("builder")
        bundle_identity = report.get("bundle")
        if not isinstance(builder, dict) or builder.get("production_eligible") is not True or builder.get("git_dirty") is not False:
            raise AssetVerificationError("production bundle report is not eligible")
        if not isinstance(bundle_identity, dict):
            raise AssetVerificationError("production bundle report has no bundle identity")
        if bundle_identity.get("archive_sha256") != sha256_file(bundle_archive):
            raise AssetVerificationError("production bundle archive differs from its report")
        if bundle_identity.get("manifest_sha256") != sha256_file(bundle_manifest):
            raise AssetVerificationError("production bundle manifest differs from its report")
    extracted = data_dir.parent / "production-bundle-extracted"
    safe_extract(bundle_archive, extracted)
    embedded = extracted / "manifest.json"
    if not embedded.is_file() or embedded.read_bytes() != manifest_bytes:
        raise AssetVerificationError("production bundle archive and detached manifest differ")
    bundle_id = str(manifest["bundle_id"])
    destination = data_dir / "bundles" / storage_name(bundle_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(extracted), destination)
    write_json(
        data_dir / "active-bundle.json",
        {"schema_version": 1, "active_bundle_id": bundle_id, "previous_bundle_id": None},
    )
    return manifest


def verify_production_manifest(
    manifest: dict[str, object],
    *,
    expected_cli: str | None,
    expected_tldr_revision: str | None,
    expected_model_revision: str | None,
) -> None:
    if expected_cli and manifest.get("cli_compatibility") != expected_cli:
        raise AssetVerificationError("staged production bundle CLI compatibility is not pinned")
    source = manifest.get("source")
    if expected_tldr_revision and (
        not isinstance(source, dict) or source.get("revision") != expected_tldr_revision
    ):
        raise AssetVerificationError("staged production bundle tldr revision is not pinned")
    model = manifest.get("embedding_model")
    if expected_model_revision and (
        not isinstance(model, dict) or model.get("revision") != expected_model_revision
    ):
        raise AssetVerificationError("staged production bundle model revision is not pinned")


def verify_archive_identity(
    extracted: Path,
    binary_name: str,
    expected_version: str | None,
    runtime_report_path: Path | None = None,
    source_runtime_report_path: Path | None = None,
    runtime_provision_report_path: Path | None = None,
) -> dict[str, object]:
    manifest_path = extracted / "release-asset-manifest.json"
    if not manifest_path.is_file():
        raise AssetVerificationError("release archive has no release-asset-manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    binary = _archive_member_path(extracted, binary_name, "shipping binary")
    if not binary.is_file():
        raise AssetVerificationError(f"release archive has no shipping binary: {binary_name}")
    binary_identity = manifest.get("binary")
    runtime = manifest.get("onnx_runtime")
    if not isinstance(binary_identity, dict):
        raise AssetVerificationError("release archive has no binary identity")
    packaged_sha256 = binary_identity.get("packaged_sha256", binary_identity.get("sha256"))
    source_sha256 = binary_identity.get("source_sha256")
    if not isinstance(packaged_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", packaged_sha256):
        raise AssetVerificationError("release archive has no packaged binary SHA256")
    if not isinstance(source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise AssetVerificationError("release archive has no source binary SHA256")
    if binary_identity.get("sha256") != packaged_sha256 or packaged_sha256 != sha256_file(binary):
        raise AssetVerificationError("release binary digest differs from archive manifest")
    if binary_identity.get("path") != binary_name:
        raise AssetVerificationError("release binary path differs from archive manifest")
    if not isinstance(runtime, dict):
        raise AssetVerificationError("release archive has no runtime identity")
    runtime_path = _archive_member_path(extracted, runtime.get("library"), "packaged ONNX Runtime")
    if not runtime_path.is_file() or runtime.get("sha256") != sha256_file(runtime_path):
        raise AssetVerificationError("packaged ONNX Runtime digest differs from archive manifest")
    if expected_version and runtime.get("version") != expected_version:
        raise AssetVerificationError("packaged ONNX Runtime version is not pinned")
    licenses = manifest.get("licenses")
    if not isinstance(licenses, list) or not licenses:
        raise AssetVerificationError("release archive is missing ONNX Runtime license records")
    for license_record in licenses:
        if not isinstance(license_record, dict):
            raise AssetVerificationError("invalid release archive license record")
        license_path = _archive_member_path(extracted, license_record.get("path"), "release license")
        if not license_path.is_file() or license_record.get("sha256") != sha256_file(license_path):
            raise AssetVerificationError("release archive license digest mismatch")
    if runtime_report_path:
        report = json.loads(runtime_report_path.read_text(encoding="utf-8"))
        reported_runtime = report.get("onnx_runtime")
        if not isinstance(reported_runtime, dict):
            raise AssetVerificationError("packaged runtime evidence has no runtime identity")
        if reported_runtime.get("version") != runtime.get("version"):
            raise AssetVerificationError("packaged runtime report version differs from archive")
        if reported_runtime.get("library_sha256") != runtime.get("sha256"):
            raise AssetVerificationError("packaged runtime report SHA differs from archive")
        if reported_runtime.get("binary_sha256") != packaged_sha256:
            raise AssetVerificationError("packaged runtime report binary SHA differs from archive")
        reported_library_path = reported_runtime.get("library_path")
        if not isinstance(reported_library_path, str) or Path(reported_library_path).name != runtime.get("library"):
            raise AssetVerificationError("packaged runtime report path differs from archive runtime")
        shipping = report.get("shipping_binary")
        if not isinstance(shipping, dict):
            raise AssetVerificationError("packaged runtime report has no shipping binary identity")
        reported_binary_path = shipping.get("path")
        if not isinstance(reported_binary_path, str) or Path(reported_binary_path).name != binary_name:
            raise AssetVerificationError("packaged runtime report path differs from archive binary")
        linkage = shipping.get("linkage") if isinstance(shipping, dict) else None
        if not isinstance(linkage, dict) or linkage.get("linkage_verified") is not True:
            raise AssetVerificationError("packaged runtime report did not verify binary linkage")
    source_report_digest = manifest.get("source_runtime_report_sha256")
    if source_report_digest:
        if source_runtime_report_path is None:
            raise AssetVerificationError("release archive source runtime evidence is missing")
        if sha256_file(source_runtime_report_path) != source_report_digest:
            raise AssetVerificationError("source runtime evidence differs from archive manifest")
        source_report = json.loads(source_runtime_report_path.read_text(encoding="utf-8"))
        source_runtime = source_report.get("onnx_runtime")
        source_shipping = source_report.get("shipping_binary")
        if not isinstance(source_runtime, dict) or not isinstance(source_shipping, dict):
            raise AssetVerificationError("source runtime report has incomplete identity")
        if source_runtime.get("version") != runtime.get("version"):
            raise AssetVerificationError("source runtime report version differs from archive")
        if source_runtime.get("library_sha256") != runtime.get("sha256"):
            raise AssetVerificationError("source runtime report SHA differs from archive")
        if source_shipping.get("sha256") != source_sha256:
            raise AssetVerificationError("source runtime report binary SHA differs from archive")
    provision_digest = manifest.get("source_runtime_provision_report_sha256")
    if provision_digest:
        if runtime_provision_report_path is None:
            raise AssetVerificationError("release archive pinned runtime evidence is missing")
        if sha256_file(runtime_provision_report_path) != provision_digest:
            raise AssetVerificationError("pinned runtime evidence differs from archive manifest")
        provision_report = json.loads(runtime_provision_report_path.read_text(encoding="utf-8"))
        provision_runtime = provision_report.get("runtime")
        provision_archive = provision_report.get("archive")
        provision_licenses = provision_report.get("licenses")
        if not isinstance(provision_runtime, dict) or not isinstance(provision_archive, dict):
            raise AssetVerificationError("pinned runtime evidence has incomplete identity")
        if provision_report.get("version") != runtime.get("version"):
            raise AssetVerificationError("pinned runtime evidence version differs from archive")
        if provision_runtime.get("library_sha256") != runtime.get("sha256"):
            raise AssetVerificationError("pinned runtime evidence SHA differs from archive")
        archive_sha = provision_archive.get("sha256")
        if not isinstance(archive_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", archive_sha):
            raise AssetVerificationError("pinned runtime evidence has no archive SHA256")
        if not isinstance(provision_licenses, list) or not provision_licenses:
            raise AssetVerificationError("pinned runtime evidence has no license records")
        pinned_license_digests = {
            record.get("sha256")
            for record in provision_licenses
            if isinstance(record, dict)
        }
        archive_license_digests = {
            record.get("sha256")
            for record in licenses
            if isinstance(record, dict)
        }
        if not pinned_license_digests.issubset(archive_license_digests):
            raise AssetVerificationError("archive licenses differ from pinned runtime evidence")
    return {
        "manifest": manifest,
        "binary": binary,
        "runtime": runtime,
        "source_binary_sha256": source_sha256,
        "packaged_binary_sha256": packaged_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument(
        "--extract-dir",
        type=Path,
        help="reuse and validate this caller-owned extraction directory",
    )
    parser.add_argument("--runtime-report", type=Path, required=True)
    parser.add_argument("--source-runtime-report", type=Path)
    parser.add_argument("--runtime-provision-report", type=Path)
    parser.add_argument("--bundle-archive", type=Path, required=True)
    parser.add_argument("--bundle-manifest", type=Path, required=True)
    parser.add_argument("--bundle-report", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--binary-name", required=True)
    parser.add_argument("--expected-runtime-version", default=os.environ.get("ORT_EXPECTED_VERSION"))
    parser.add_argument("--expected-cli-compatibility", default="askman=0.4.0")
    parser.add_argument("--expected-tldr-revision", default="e7186598dc466e69c2adf5d8f06037d5b186f08d")
    parser.add_argument("--expected-model-revision", default="5f1b8cd78bc4fb444dd171e59b18f3a3af89a079")
    parser.add_argument("--network-probe-state", type=Path, required=True)
    parser.add_argument("--network-policy", required=True)
    args = parser.parse_args()

    args.report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="askman-production-verify-") as directory:
        root = Path(directory)
        if args.extract_dir:
            extracted = args.extract_dir.resolve()
            validate_existing_extraction(args.archive.resolve(), extracted)
        else:
            extracted = root / "asset"
            safe_extract(args.archive.resolve(), extracted)
        identity = verify_archive_identity(
            extracted,
            args.binary_name,
            args.expected_runtime_version,
            args.runtime_report.resolve(),
            args.source_runtime_report.resolve() if args.source_runtime_report else None,
            args.runtime_provision_report.resolve() if args.runtime_provision_report else None,
        )
        binary = Path(identity["binary"])
        runtime_environment = archive_runtime_environment(
            extracted,
            args.expected_runtime_version,
        )
        archive_runtime_evidence = capture_archive_runtime_identity(
            extracted,
            binary,
            args.expected_runtime_version,
            identity["manifest"],
        )
        network_evidence: dict[str, object] = {"validated": False}
        if args.network_probe_state:
            if not args.network_policy or not any(
                args.network_policy.startswith(prefix)
                for prefix in ("Linux iptables", "macOS sandbox-exec", "Windows program-specific")
            ):
                raise AssetVerificationError("production verification requires a recognized OS network policy")
            probe_payload = json.loads(args.network_probe_state.read_text(encoding="utf-8"))
            if probe_payload.get("connections") != 0:
                raise AssetVerificationError("network denial probe recorded an accepted connection")
            network_evidence = {
                "validated": True,
                "policy": args.network_policy,
                "probe_connections": probe_payload.get("connections"),
            }
        data_dir = root / "askman-data"
        manifest = stage_bundle(
            args.bundle_archive.resolve(),
            args.bundle_manifest.resolve(),
            data_dir,
            args.bundle_report.resolve(),
        )
        verify_production_manifest(
            manifest,
            expected_cli=args.expected_cli_compatibility,
            expected_tldr_revision=args.expected_tldr_revision,
            expected_model_revision=args.expected_model_revision,
        )
        query_records: list[dict[str, object]] = []
        for policy, flags, query, expected_platform, expected_source in TARGET_QUERIES:
            returncode, output = run_binary(
                binary,
                ["--ci-json-v1", *flags, *query.split()],
                data_dir,
                args.report_dir,
                f"query-{policy}",
                runtime_environment,
            )
            if returncode != 0:
                raise AssetVerificationError(f"packaged shipping query failed for {policy}: exit {returncode}")
            results = parse_shipping_json(output, f"packaged shipping query {policy}")
            if not results or results[0].get("platform") != expected_platform or results[0].get("source_path") != expected_source:
                raise AssetVerificationError(f"packaged shipping query mismatch for {policy}")
            query_records.append(
                {
                    "policy": policy,
                    "flags": list(flags),
                    "query": query,
                    "top_platform": results[0].get("platform"),
                    "top_source_path": results[0].get("source_path"),
                    "result_count": len(results),
                    "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                }
            )

        # A missing active bundle must fail closed.  A state with no previous
        # bundle must also reject rollback rather than silently changing data.
        broken_data = root / "broken-data"
        shutil.copytree(data_dir, broken_data)
        (broken_data / "active-bundle.json").write_text(
            json.dumps({"schema_version": 1, "active_bundle_id": "missing", "previous_bundle_id": None}),
            encoding="utf-8",
        )
        returncode, _ = run_binary(
            binary,
            ["--ci-json-v1", "copy", "files"],
            broken_data,
            args.report_dir,
            "failure-tampered-state",
            runtime_environment,
        )
        if returncode == 0:
            raise AssetVerificationError("packaged shipping binary accepted a missing active bundle")
        returncode, _ = run_binary(
            binary,
            ["rollback"],
            data_dir,
            args.report_dir,
            "rollback-without-previous",
            runtime_environment,
        )
        if returncode == 0:
            raise AssetVerificationError("packaged shipping binary accepted rollback without a previous bundle")

        write_json(
            args.report_dir / "production-verification.json",
            {
                "status": "passed",
                "archive": str(args.archive.resolve()),
                "asset_name": args.archive.name,
                "archive_sha256": sha256_file(args.archive.resolve()),
                "bundle_manifest_sha256": sha256_file(args.bundle_manifest.resolve()),
                "bundle": manifest,
                "asset": identity["manifest"],
                "archive_runtime": archive_runtime_evidence,
                "queries": query_records,
                "failure_check": "tampered active state rejected",
                "rollback_check": "rollback without previous bundle rejected",
                "network_isolation": network_evidence,
            },
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, tarfile.TarError, AssetVerificationError) as error:
        raise SystemExit(f"production asset verification failed: {error}") from error
