import hashlib
import json
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
    VerificationError,
    create_checksum_invalid_bundle_archive,
    create_partial_bundle_archive,
    parse_shipping_json,
    require_runtime_identity,
    runtime_metadata,
    network_probe_evidence,
    storage_name,
    validate_network_probe_payload,
    _runtime_linkage,
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

    def test_network_probe_validator_rejects_malformed_external_state(self):
        valid = {
            "mode": "external",
            "url": "https://github.com/",
            "nonce": "nonce-1",
            "baseline_succeeded": True,
            "denied": True,
            "accepted": False,
            "connections": 0,
            "error_classification": "windows-firewall",
        }
        self.assertIs(
            validate_network_probe_payload(
                valid,
                expected_nonce="nonce-1",
                require_external=True,
            ),
            valid,
        )
        for field, value in (
            ("url", "http://github.com/"),
            ("nonce", "wrong-nonce"),
            ("baseline_succeeded", False),
            ("denied", False),
            ("accepted", True),
            ("connections", False),
            ("error_classification", "network-error"),
        ):
            malformed = valid.copy()
            malformed[field] = value
            with self.assertRaisesRegex(
                VerificationError,
                "external network denial probe state is invalid",
            ):
                validate_network_probe_payload(malformed, expected_nonce="nonce-1")
        with self.assertRaisesRegex(VerificationError, "requires an external"):
            validate_network_probe_payload(
                {"connections": 0},
                expected_nonce="nonce-1",
                require_external=True,
            )

    def test_windows_network_policy_rejects_legacy_local_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "local.json"
            state.write_text(
                json.dumps({"host": "127.0.0.1", "port": 1234, "connections": 0}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "ASKMAN_CI_NETWORK_PROBE_STATE": str(state),
                    "ASKMAN_CI_NETWORK_POLICY": "Windows program-specific outbound firewall",
                    "ASKMAN_CI_NETWORK_PROBE_NONCE": "nonce-1",
                },
                clear=False,
            ):
                with self.assertRaisesRegex(VerificationError, "requires an external"):
                    network_probe_evidence(required=True)

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

    def test_runtime_identity_prefers_windows_colocated_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provisioned = root / "provisioned"
            binary_directory = root / "target" / "release"
            provisioned.mkdir()
            binary_directory.mkdir(parents=True)
            library = provisioned / "onnxruntime.dll"
            colocated = binary_directory / "onnxruntime.dll"
            binary = binary_directory / "askman.exe"
            library.write_bytes(b"runtime")
            colocated.write_bytes(b"runtime")
            binary.write_bytes(b"binary")
            completed = SimpleNamespace(stdout="  DLL Name: onnxruntime.dll\n", returncode=0)
            conflicting = root / "cwd" / "onnxruntime.dll"
            conflicting.parent.mkdir()
            conflicting.write_bytes(b"wrong-runtime")

            def find_tool(name):
                return "/usr/bin/objdump" if name == "objdump" else None

            previous_cwd = Path.cwd()
            os.chdir(conflicting.parent)
            try:
                with (
                    patch.dict(
                        os.environ,
                        {
                            "ORT_EXPECTED_VERSION": "1.20.0",
                            "ORT_LIB_LOCATION": str(provisioned),
                        },
                        clear=False,
                    ),
                    patch("scripts.ci_offline.platform.system", return_value="Windows"),
                    patch("scripts.ci_offline.shutil.which", side_effect=find_tool),
                    patch("scripts.ci_offline.subprocess.run", return_value=completed),
                ):
                    evidence = runtime_metadata({"shipping": binary})
                    require_runtime_identity(evidence, expected_version="1.20.0")
            finally:
                os.chdir(previous_cwd)

            runtime = evidence["onnx_runtime"]
            linkage = evidence["binaries"]["shipping"]["linkage"]
            self.assertEqual(runtime["resolution"], "binary-linkage")
            self.assertEqual(Path(runtime["library_path"]), colocated.resolve())
            self.assertNotEqual(Path(runtime["library_path"]), library.resolve())
            self.assertEqual(runtime["library_sha256"], hashlib.sha256(b"runtime").hexdigest())
            self.assertTrue(linkage["linkage_verified"])

    def test_runtime_identity_keeps_windows_dependency_before_output_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provisioned = root / "provisioned"
            binary_directory = root / "target" / "release"
            provisioned.mkdir()
            binary_directory.mkdir(parents=True)
            library = provisioned / "onnxruntime.dll"
            colocated = binary_directory / "onnxruntime.dll"
            binary = binary_directory / "askman.exe"
            library.write_bytes(b"runtime")
            colocated.write_bytes(b"runtime")
            binary.write_bytes(b"binary")
            completed = SimpleNamespace(
                stdout="  DLL Name: onnxruntime.dll\n" + ("unrelated symbol\n" * 1000),
                returncode=0,
            )

            def find_tool(name):
                return "/usr/bin/llvm-objdump" if name == "llvm-objdump" else None

            with (
                patch.dict(
                    os.environ,
                    {
                        "ORT_EXPECTED_VERSION": "1.20.0",
                        "ORT_LIB_LOCATION": str(provisioned),
                    },
                    clear=False,
                ),
                patch("scripts.ci_offline.platform.system", return_value="Windows"),
                patch("scripts.ci_offline.shutil.which", side_effect=find_tool),
                patch("scripts.ci_offline.subprocess.run", return_value=completed),
            ):
                evidence = runtime_metadata({"shipping": binary})
                require_runtime_identity(evidence, expected_version="1.20.0")

            runtime = evidence["onnx_runtime"]
            self.assertEqual(runtime["resolution"], "binary-linkage")
            self.assertEqual(Path(runtime["library_path"]), colocated.resolve())

    def test_windows_linkage_tool_selection_prefers_dumpbin_then_llvm_objdump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "askman.exe"
            library = root / "onnxruntime.dll"
            binary.write_bytes(b"binary")
            library.write_bytes(b"runtime")
            completed = SimpleNamespace(stdout="onnxruntime.dll\n", returncode=0)

            def find_dumpbin(name):
                return "/usr/bin/dumpbin" if name == "dumpbin" else None

            with (
                patch("scripts.ci_offline.platform.system", return_value="Windows"),
                patch("scripts.ci_offline.shutil.which", side_effect=find_dumpbin),
                patch("scripts.ci_offline.subprocess.run", return_value=completed),
            ):
                dumpbin_linkage = _runtime_linkage(binary, library)

            def find_llvm_objdump(name):
                return "/usr/bin/llvm-objdump" if name == "llvm-objdump" else None

            with (
                patch("scripts.ci_offline.platform.system", return_value="Windows"),
                patch("scripts.ci_offline.shutil.which", side_effect=find_llvm_objdump),
                patch("scripts.ci_offline.subprocess.run", return_value=completed),
            ):
                llvm_objdump_linkage = _runtime_linkage(binary, library)

            self.assertEqual(dumpbin_linkage["command"][1], "/DEPENDENTS")
            self.assertEqual(llvm_objdump_linkage["command"][1], "-p")

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
