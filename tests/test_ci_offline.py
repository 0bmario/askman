import hashlib
import os
import platform
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.ci_offline import (
    TARGET_QUERIES,
    create_checksum_invalid_bundle_archive,
    create_partial_bundle_archive,
    parse_shipping_json,
    require_runtime_identity,
    runtime_metadata,
    storage_name,
)


class OfflineLifecycleFixtureTests(unittest.TestCase):
    def test_storage_name_matches_bundle_store_encoding(self):
        self.assertEqual(storage_name("matching-bundle-v2:abc"), "matching-bundle-v2%3aabc")

    def test_failure_archives_are_deterministic_and_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            bundle.mkdir()
            (bundle / "manifest.json").write_bytes(b"manifest")
            (bundle / "matching.db").write_bytes(b"database")
            partial = root / "partial.tar.gz"
            corrupt = root / "checksum-invalid.tar.gz"

            create_partial_bundle_archive(bundle, partial)
            create_checksum_invalid_bundle_archive(bundle, corrupt)

            with tarfile.open(partial, "r:gz") as archive:
                self.assertEqual(archive.getnames(), ["manifest.json"])
            with tarfile.open(corrupt, "r:gz") as archive:
                payload = archive.extractfile("matching.db")
                self.assertIsNotNone(payload)
                self.assertEqual(payload.read(), b"databasd")

    def test_shipping_json_requires_structured_results(self):
        results = parse_shipping_json(
            '[{"platform":"linux","source_path":"pages/linux/grep.md"}]',
            "probe",
        )
        self.assertEqual(results[0]["source_path"], "pages/linux/grep.md")
        historical = parse_shipping_json(
            '{"query":"search files","results":[{"platform":"linux","source_path":"pages/linux/grep.md"}]}',
            "historical",
        )
        self.assertEqual(historical[0]["platform"], "linux")
        with self.assertRaisesRegex(RuntimeError, "shipping CLI JSON"):
            parse_shipping_json("grep\nno structured output", "probe")

    def test_target_queries_have_platform_and_source_expectations(self):
        self.assertEqual(
            [(name, expected_platform, expected_source) for name, _, _, expected_platform, expected_source in TARGET_QUERIES],
            [
                ("common", "common", "pages/common/cp.md"),
                ("linux", "linux", "pages/linux/grep.md"),
                ("osx", "osx", "pages/osx/pbcopy.md"),
                ("windows", "windows", "pages/windows/printf.md"),
            ],
        )

    def test_runtime_metadata_records_binary_and_runtime_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suffix = {
                "Darwin": ".dylib",
                "Linux": ".so",
                "Windows": ".dll",
            }.get(platform.system(), ".so")
            library = root / f"libonnxruntime.1.20.0{suffix}"
            binary = root / "askman"
            library.write_bytes(b"runtime")
            binary.write_bytes(b"binary")
            previous = os.environ.get("ORT_LIB_LOCATION")
            os.environ["ORT_LIB_LOCATION"] = str(root)
            try:
                evidence = runtime_metadata({"shipping": binary})
            finally:
                if previous is None:
                    os.environ.pop("ORT_LIB_LOCATION", None)
                else:
                    os.environ["ORT_LIB_LOCATION"] = previous
            runtime = evidence["onnx_runtime"]
            self.assertEqual(runtime["version"], "1.20.0")
            self.assertIsNotNone(runtime["library_sha256"])
            self.assertEqual(
                evidence["binaries"]["shipping"]["sha256"],
                hashlib.sha256(b"binary").hexdigest(),
            )

    def test_runtime_identity_accepts_linux_runtime_soname_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / "libonnxruntime.so.1.20.0"
            soname = root / "libonnxruntime.so.1"
            binary = root / "askman"
            library.write_bytes(b"runtime")
            soname.symlink_to(library.name)
            binary.write_bytes(b"binary")
            ldd_output = f"libonnxruntime.so.1 => {soname} (0x00007f)\n"
            completed = SimpleNamespace(stdout=ldd_output, returncode=0)
            with (
                patch.dict(os.environ, {"ORT_LIB_LOCATION": str(root)}, clear=False),
                patch("scripts.ci_offline.platform.system", return_value="Linux"),
                patch("scripts.ci_offline.shutil.which", return_value="/usr/bin/ldd"),
                patch("scripts.ci_offline.subprocess.run", return_value=completed),
            ):
                evidence = runtime_metadata({"shipping": binary})
                require_runtime_identity(evidence, expected_version="1.20.0")

            runtime = evidence["onnx_runtime"]
            linkage = evidence["binaries"]["shipping"]["linkage"]
            self.assertEqual(Path(runtime["library_path"]), library.resolve())
            self.assertEqual(runtime["library_sha256"], hashlib.sha256(b"runtime").hexdigest())
            self.assertTrue(linkage["linkage_verified"])

    def test_runtime_identity_rejects_unverified_linkage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / "libonnxruntime.1.20.0.so"
            binary = root / "askman"
            library.write_bytes(b"runtime")
            binary.write_bytes(b"binary")
            evidence = {
                "onnx_runtime": {
                    "version": "1.20.0",
                    "library_path": str(library),
                    "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
                    "resolution": "binary-linkage",
                },
                "binaries": {
                    "shipping": {
                        "path": str(binary),
                        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                        "linkage": {"linkage_verified": False},
                    }
                },
            }
            with self.assertRaisesRegex(RuntimeError, "linkage"):
                require_runtime_identity(evidence)


if __name__ == "__main__":
    unittest.main()
