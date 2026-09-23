import unittest

from scripts.provision_onnxruntime import RUNTIME_ASSETS, VERSION


class OnnxRuntimeProvisionTests(unittest.TestCase):
    def test_all_release_targets_have_authoritative_identity_pins(self):
        self.assertEqual(VERSION, "1.20.0")
        self.assertEqual(
            set(RUNTIME_ASSETS),
            {
                "x86_64-unknown-linux-gnu",
                "x86_64-apple-darwin",
                "aarch64-apple-darwin",
                "x86_64-pc-windows-msvc",
            },
        )
        for target, asset in RUNTIME_ASSETS.items():
            self.assertTrue(str(asset["archive_name"]).endswith((".tgz", ".zip")), target)
            for key in ("archive_sha256", "library_sha256", "license_sha256", "notice_sha256"):
                self.assertRegex(str(asset[key]), r"^[0-9a-f]{64}$", f"{target}:{key}")
            self.assertIn(asset["loader_variable"], {"LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "PATH"})


if __name__ == "__main__":
    unittest.main()
