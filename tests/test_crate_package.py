import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.verify_crate_package import PackageError, verify_package


ROOT = Path(__file__).resolve().parents[1]


class CratePackageTests(unittest.TestCase):
    def test_package_verifier_accepts_current_crate_and_reports_digest(self):
        package = ROOT / "target/package/askman-0.4.0.crate"
        if not package.is_file():
            self.skipTest("cargo package artifact not present; release workflow runs this check")
        report = verify_package(package, "0.4.0")
        self.assertEqual(report["package"], "askman-0.4.0.crate")
        self.assertEqual(len(report["archive_sha256"]), 64)
        self.assertTrue(report["mutable_assets_excluded"])
        self.assertNotIn("matching.db", " ".join(report["members"]))
        self.assertNotIn("model-cache", " ".join(report["members"]))

    def test_package_verifier_rejects_mutable_database_member(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "askman-0.4.0.crate"
            prefix = "askman-0.4.0/"
            members = {
                "Cargo.toml": b"[package]\nname = 'askman'\nversion = '0.4.0'\n",
                "Cargo.lock": b'name = "askman"\nversion = "0.4.0"\n',
                "LICENSE": b"license",
                "README.md": b"readme",
                "src/lib.rs": b"pub fn value() {}\n",
                "src/main.rs": b"fn main() {}\n",
                "matching.db": b"mutable database",
            }
            with tarfile.open(package, "w:gz") as archive:
                for name, payload in members.items():
                    info = tarfile.TarInfo(prefix + name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            with self.assertRaises(PackageError):
                verify_package(package, "0.4.0")

    def test_package_manifest_declares_a_code_only_include(self):
        cargo = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
        self.assertIn('"src/**"', cargo)
        self.assertNotIn('"target/**"', cargo)
        self.assertNotIn('"model-cache/**"', cargo)
        self.assertNotIn('"*.db"', cargo)


if __name__ == "__main__":
    unittest.main()
