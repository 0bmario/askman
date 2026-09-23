import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

from scripts.verify_release_asset import (
    archive_runtime_environment,
    validate_existing_extraction,
    verify_archive_identity,
)


ROOT = Path(__file__).resolve().parents[1]


class ReleaseAssetTests(unittest.TestCase):
    def test_archive_runtime_environment_discards_inherited_cache_paths(self):
        previous = {
            name: os.environ.get(name)
            for name in (
                "LD_LIBRARY_PATH",
                "DYLD_LIBRARY_PATH",
                "ORT_LIB_LOCATION",
                "ORT_LIBRARY_PATH",
                "ORT_ROOT",
                "XDG_CACHE_HOME",
                "LOCALAPPDATA",
                "PROGRAMDATA",
                "PATH",
            )
        }
        try:
            for name in previous:
                os.environ[name] = "/cache-backed-runtime"
            environment = archive_runtime_environment(Path("/tmp/archive"), "1.20.0")
            self.assertEqual(environment["ORT_LIB_LOCATION"], "/tmp/archive")
            self.assertEqual(environment["ORT_LIBRARY_PATH"], "/tmp/archive")
            self.assertEqual(environment["ORT_ROOT"], "/tmp/archive")
            for name in previous:
                if name not in {"ORT_LIB_LOCATION", "ORT_LIBRARY_PATH", "ORT_ROOT", "PATH"}:
                    self.assertNotIn(name, environment)
            self.assertTrue(environment["PATH"].split(os.pathsep)[0] == "/tmp/archive")
            self.assertNotIn("cache-backed-runtime", environment["PATH"])
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_windows_archive_contains_runtime_and_license(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "askman.exe"
            runtime = root / "onnxruntime.dll"
            license_path = root / "LICENSE"
            binary.write_bytes(b"shipping-binary")
            runtime.write_bytes(b"pinned-runtime")
            license_path.write_text("pinned license\n", encoding="utf-8")
            report_dir = root / "report"
            report_dir.mkdir()
            write_runtime_report = {
                "verification_status": "runtime-identity",
                "onnx_runtime": {
                    "version": "1.20.0",
                    "library_path": str(runtime),
                    "library_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
                    "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                },
                "shipping_binary": {
                    "path": str(binary),
                    "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                },
            }
            report = report_dir / "runtime-metadata.json"
            report.write_text(json.dumps(write_runtime_report), encoding="utf-8")
            archive = root / "askman-windows-x86_64.tar.gz"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/package_release_asset.py"),
                    "--binary",
                    str(binary),
                    "--runtime-report",
                    str(report),
                    "--output",
                    str(archive),
                    "--system",
                    "Windows",
                    "--license",
                    str(license_path),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            )
            with tempfile.TemporaryDirectory() as extracted_dir:
                extracted = Path(extracted_dir)
                with tarfile.open(archive, "r:gz") as stream:
                    stream.extractall(extracted)
                validate_existing_extraction(archive, extracted)
                identity = verify_archive_identity(
                    extracted,
                    "askman.exe",
                    "1.20.0",
                    source_runtime_report_path=report,
                )
                self.assertEqual(identity["runtime"]["library"], "onnxruntime.dll")
                self.assertEqual(
                    identity["manifest"]["binary"]["packaged_sha256"],
                    identity["manifest"]["binary"]["sha256"],
                )
                self.assertEqual(
                    identity["manifest"]["binary"]["source_sha256"],
                    hashlib.sha256(binary.read_bytes()).hexdigest(),
                )
                self.assertTrue((extracted / "licenses/onnxruntime-LICENSE.txt").is_file())

    def test_network_probe_records_an_accepted_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "probe.json"
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "scripts/network_probe.py"), "server", "--state", str(state)],
                cwd=ROOT,
            )
            try:
                for _ in range(30):
                    if state.is_file():
                        break
                    time.sleep(0.05)
                payload = json.loads(state.read_text(encoding="utf-8"))
                url = f"http://{payload['host']}:{payload['port']}"
                completed = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/network_probe.py"), "request", "--url", url],
                    cwd=ROOT,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0)
                for _ in range(30):
                    if json.loads(state.read_text(encoding="utf-8"))["connections"]:
                        break
                    time.sleep(0.05)
                self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["connections"], 1)
            finally:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
