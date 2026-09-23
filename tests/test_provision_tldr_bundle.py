import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "provision_tldr_bundle", ROOT / "scripts/provision_tldr_bundle.py"
)
PROVISION = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PROVISION)


class ProvisionTldrBundleTests(unittest.TestCase):
    def test_production_manifest_is_exhaustive_and_explicit(self):
        manifest = json.loads(PROVISION.MANIFEST_PATH.read_text(encoding="utf-8"))
        files = manifest["files"]
        exclusions = manifest["exclusions"]
        self.assertEqual(files, sorted(files))
        self.assertEqual(len(files), 7415)
        self.assertEqual(len(exclusions), 57)
        self.assertEqual(len({item["path"] for item in exclusions}), 57)
        self.assertTrue(all(item["path"] in files for item in exclusions))
        self.assertTrue(all(item["reason"].strip() for item in exclusions))
        self.assertEqual(manifest["source"]["revision"], PROVISION.UPSTREAM_REVISION)
        self.assertEqual(manifest["parser_version"], PROVISION.PARSER_VERSION)
        self.assertEqual(manifest["language"], "en")
        self.assertEqual(manifest["source"]["license"]["name"], "CC-BY-4.0")
        self.assertEqual(manifest["source"]["license"]["url"], PROVISION.TLDR_LICENSE_URL)
        self.assertEqual(manifest["source"]["attribution"], PROVISION.TLDR_ATTRIBUTION)
        self.assertEqual(manifest["source"]["url"], PROVISION.UPSTREAM_SOURCE_URL)
        self.assertEqual(
            manifest["provisioning"]["exclusions_sha256"],
            PROVISION.EXPECTED_EXCLUSIONS_SHA256,
        )
        self.assertEqual(
            PROVISION.exclusions_digest(exclusions),
            PROVISION.EXPECTED_EXCLUSIONS_SHA256,
        )
        self.assertEqual(
            PROVISION.sha256_file(PROVISION.MANIFEST_PATH),
            PROVISION.EXPECTED_MANIFEST_SHA256,
        )

    def test_platform_probes_pin_target_specific_source_precedence(self):
        self.assertEqual(
            {
                platform: (probe["expected_platform"], probe["expected_source_path"])
                for platform, probe in PROVISION.DEFAULT_PROBES.items()
            },
            {
                "common": ("common", "pages/common/qcp.md"),
                "linux": ("linux", "pages/linux/rc-service.md"),
                "osx": ("osx", "pages/osx/say.md"),
                "windows": ("windows", "pages/windows/copy.md"),
            },
        )
        self.assertEqual(
            PROVISION.HYBRID_PROBES["collision_target_precedence"]["expected_source_path"],
            "pages/windows/copy.md",
        )
        self.assertEqual(
            PROVISION.HYBRID_PROBES["collision_target_precedence"]["query"],
            "copy a file to another location",
        )
        self.assertEqual(
            PROVISION.HYBRID_PROBES["collision_common_fallback"]["expected_source_path"],
            "pages/common/qcp.md",
        )
        self.assertIsNone(PROVISION.HYBRID_PROBES["collision_common_fallback"]["flag"])
        self.assertEqual(
            PROVISION.HYBRID_PROBES["collision_common_fallback"]["query"],
            "copy multiple JPEG files",
        )

    def test_detached_manifest_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            internal = root / "manifest.json"
            detached = root / "release" / "matching-bundle-manifest.json"
            bundle = root / "bundle"
            bundle.mkdir()
            internal.write_bytes(b'{"bundle_id":"test"}\n')
            digest = PROVISION.emit_detached_manifest(internal, detached, bundle)
            self.assertEqual(detached.read_bytes(), internal.read_bytes())
            self.assertEqual(digest, hashlib.sha256(internal.read_bytes()).hexdigest())

    def test_detached_manifest_rejects_symlinks_and_bundle_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            internal = root / "manifest.json"
            bundle = root / "bundle"
            bundle.mkdir()
            internal.write_bytes(b"manifest")
            with self.assertRaises(PROVISION.ProvisionError):
                PROVISION.emit_detached_manifest(
                    internal, bundle / "matching-bundle-manifest.json", bundle
                )
            bundle_link = root / "bundle-link"
            bundle_link.symlink_to(bundle, target_is_directory=True)
            with self.assertRaises(PROVISION.ProvisionError):
                PROVISION.emit_detached_manifest(
                    internal, bundle_link / "matching-bundle-manifest.json", bundle
                )
            target = root / "target"
            target.write_bytes(b"old")
            symlink = root / "link"
            symlink.symlink_to(target)
            with self.assertRaises(PROVISION.ProvisionError):
                PROVISION.emit_detached_manifest(internal, symlink, bundle)

    def test_pinned_model_license_notice_is_exact(self):
        notice = PROVISION.verify_model_license_notice()
        self.assertEqual(notice["sha256"], PROVISION.MODEL_NOTICE_SHA256)
        self.assertEqual(notice["size_bytes"], 945)
        self.assertEqual(notice["license"], "Apache-2.0")

    def test_runtime_identity_is_mandatory(self):
        with self.assertRaises(PROVISION.ProvisionError):
            PROVISION.verify_runtime(None, None, None, {})

    def test_runtime_identity_verifies_both_shipping_binaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            archive = root / "onnxruntime-osx-arm64-1.20.0.tgz"
            archive.write_bytes(b"archive")
            dylib = runtime / "libonnxruntime.1.20.0.dylib"
            dylib.write_bytes(b"library")
            builder = root / "tldr_subset"
            candidate = root / "askman_candidate"
            builder.write_bytes(b"builder")
            candidate.write_bytes(b"candidate")
            identity = {
                ("Darwin", "arm64"): {
                    "archive_name": archive.name,
                    "library_name": dylib.name,
                    "archive_sha256": "archive-sha",
                    "library_sha256": "library-sha",
                }
            }

            def fake_run(command, **_kwargs):
                if "-hv" in command:
                    return SimpleNamespace(stdout="Mach header ARM64")
                return SimpleNamespace(
                    stdout=f"{command[-1]}:\n\t@rpath/{dylib.name} (compatibility version 0.0.0)\n"
                )

            def fake_sha256(path):
                return "archive-sha" if Path(path).name == archive.name else "library-sha"

            with (
                patch.object(PROVISION.host_platform, "system", return_value="Darwin"),
                patch.object(PROVISION.host_platform, "machine", return_value="arm64"),
                patch.object(PROVISION, "RUNTIME_IDENTITIES", identity),
                patch.object(PROVISION, "sha256_file", side_effect=fake_sha256),
                patch.object(PROVISION.shutil, "which", return_value="otool"),
                patch.object(PROVISION.subprocess, "run", side_effect=fake_run),
            ):
                evidence = PROVISION.verify_runtime(
                    runtime,
                    archive,
                    builder,
                    {},
                    candidate,
                )

            self.assertEqual(
                set(evidence["binaries"]), {"tldr_subset", "askman_candidate"}
            )
            for binary in evidence["binaries"].values():
                self.assertTrue(binary["architecture_verified"])
                self.assertEqual(binary["linkage_verified_library_path"], str(dylib.resolve()))
                self.assertEqual(binary["linkage_verified_library_sha256"], "library-sha")

    def test_dirty_tree_requires_explicit_dev_override(self):
        with patch.object(PROVISION, "_git_bytes", return_value=b" M src/dense.rs\n"):
            with self.assertRaisesRegex(PROVISION.ProvisionError, "working tree is dirty"):
                PROVISION.verify_git_tree(False)
            state = PROVISION.verify_git_tree(True)
        self.assertTrue(state["dirty"])
        self.assertTrue(state["allow_dirty"])
        self.assertFalse(state["production_eligible"])

    def test_clean_tree_is_production_eligible_without_override(self):
        with patch.object(PROVISION, "_git_bytes", return_value=b""):
            state = PROVISION.verify_git_tree(False)
        self.assertFalse(state["dirty"])
        self.assertFalse(state["allow_dirty"])
        self.assertTrue(state["production_eligible"])

    def test_evidence_paths_are_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle" / "matching.db"
            self.assertEqual(
                PROVISION.normalize_evidence_path(path, Path(directory)),
                "${RUN_DIR}/bundle/matching.db",
            )

    def test_source_digest_is_order_independent_but_content_sensitive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pages/common").mkdir(parents=True)
            (root / "pages/linux").mkdir()
            (root / "pages/common/a.md").write_bytes(b"a")
            (root / "pages/linux/b.md").write_bytes(b"b")
            paths = ["pages/linux/b.md", "pages/common/a.md"]
            first = PROVISION.source_digest(root, paths)
            second = PROVISION.source_digest(root, list(reversed(paths)))
            self.assertEqual(first, second)
            (root / "pages/linux/b.md").write_bytes(b"changed")
            self.assertNotEqual(first, PROVISION.source_digest(root, paths))

    def test_logical_tree_digest_ignores_file_order(self):
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            first = Path(first_directory)
            second = Path(second_directory)
            for root in (first, second):
                (root / "nested").mkdir()
            (first / "a").write_bytes(b"one")
            (first / "nested/b").write_bytes(b"two")
            (second / "nested/b").write_bytes(b"two")
            (second / "a").write_bytes(b"one")
            self.assertEqual(
                PROVISION.logical_tree_digest(first),
                PROVISION.logical_tree_digest(second),
            )

    def test_deterministic_archive_has_stable_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bundle").mkdir()
            (root / "bundle/a.txt").write_text("a", encoding="utf-8")
            (root / "bundle/b.txt").write_text("b", encoding="utf-8")
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"
            PROVISION.create_deterministic_archive(root / "bundle", first)
            PROVISION.create_deterministic_archive(root / "bundle", second)
            self.assertEqual(
                hashlib.sha256(first.read_bytes()).digest(),
                hashlib.sha256(second.read_bytes()).digest(),
            )

    def test_archive_rejects_inside_bundle_and_symlink_escapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            bundle.mkdir()
            (bundle / "file.txt").write_text("data", encoding="utf-8")

            with self.assertRaisesRegex(PROVISION.ProvisionError, "outside the bundle"):
                PROVISION.create_deterministic_archive(
                    bundle, bundle / "matching-bundle.tar.gz"
                )

            bundle_link = root / "bundle-link"
            bundle_link.symlink_to(bundle, target_is_directory=True)
            with self.assertRaisesRegex(PROVISION.ProvisionError, "outside the bundle"):
                PROVISION.create_deterministic_archive(
                    bundle, bundle_link / "matching-bundle.tar.gz"
                )

            dangling = root / "dangling.tar.gz"
            dangling.symlink_to(root / "missing.tar.gz")
            with self.assertRaises(PROVISION.ProvisionError):
                PROVISION.create_deterministic_archive(bundle, dangling)
            self.assertTrue(dangling.is_symlink())

    def test_archive_refuses_existing_output_and_cleans_failed_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            bundle.mkdir()
            (bundle / "file.txt").write_text("data", encoding="utf-8")
            existing = root / "existing.tar.gz"
            existing.write_bytes(b"keep")
            with self.assertRaises(PROVISION.ProvisionError):
                PROVISION.create_deterministic_archive(bundle, existing)
            self.assertEqual(existing.read_bytes(), b"keep")

            failed = root / "failed.tar.gz"
            with patch.object(
                PROVISION,
                "_write_deterministic_archive",
                side_effect=OSError("injected archive failure"),
            ):
                with self.assertRaisesRegex(OSError, "injected archive failure"):
                    PROVISION.create_deterministic_archive(bundle, failed)
            self.assertFalse(failed.exists())
            self.assertEqual(list(root.glob(".failed.tar.gz.part")), [])


if __name__ == "__main__":
    unittest.main()
