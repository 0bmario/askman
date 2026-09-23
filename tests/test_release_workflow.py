import unittest
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/release.yml"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_version_is_consistent_across_package_and_docs(self):
        cargo = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
        lock = (ROOT / "Cargo.lock").read_text(encoding="utf-8")
        self.assertEqual(cargo["package"]["version"], "0.4.0")
        self.assertIn('name = "askman"\nversion = "0.4.0"', lock)
        self.assertIn("/v0.4.0/install.sh", (ROOT / "README.md").read_text(encoding="utf-8"))
        notes = (ROOT / "docs/releases/0.4.0.md").read_text(encoding="utf-8")
        self.assertIn("release gate", notes)
        self.assertIn("native matrix", notes)
        self.assertIn("CC-BY-4.0", notes)
        self.assertIn("Apache-2.0", notes)

    def test_release_is_explicitly_structured_for_040(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('- "v0.4.0"', workflow)
        self.assertIn("production-bundle:", workflow)
        self.assertIn("runs-on: macos-15", workflow)
        self.assertIn("os: macos-15-intel", workflow)
        self.assertIn("--cli-compatibility \"askman=${EXPECTED_RELEASE_VERSION}\"", workflow)

    def test_production_bundle_is_required_before_publish(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "needs: [build-binaries, release-readiness, production-bundle, production-verification, package-crate]",
            workflow,
        )
        self.assertIn("name: production-matching-bundle", workflow)
        self.assertIn("matching-bundle-manifest.json", workflow)
        self.assertIn("matching-bundle.tar.gz", workflow)
        self.assertIn("production bundle evidence is dirty or production-ineligible", workflow)

    def test_release_permissions_and_locked_builds_are_scoped(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("\npermissions:\n  contents: read\n", workflow)
        self.assertNotIn("\npermissions:\n  contents: write\n", workflow)
        self.assertIn("publish-release:\n    name: Publish Release", workflow)
        self.assertIn("publish-release:\n    name: Publish Release\n    needs:", workflow)
        self.assertIn("    permissions:\n      contents: write\n\n    steps:", workflow)
        self.assertEqual(workflow.count("contents: write"), 1)
        self.assertGreaterEqual(workflow.count("persist-credentials: false"), 4)
        self.assertIn("cargo fetch --locked", workflow)
        self.assertIn("cargo build --locked --release --target", workflow)

    def test_crate_package_is_verified_and_published_after_github_release(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("package-crate:", workflow)
        self.assertIn("scripts/verify_crate_package.py", workflow)
        self.assertIn("cargo install --locked --offline", workflow)
        self.assertIn("test \"$(\"$install_root/bin/askman\" --version)\" = \"askman 0.4.0\"", workflow)
        self.assertIn("publish-crate:", workflow)
        self.assertIn("needs: [publish-release]", workflow)
        self.assertIn("CARGO_REGISTRY_TOKEN: ${{ secrets.CARGO_REGISTRY_TOKEN }}", workflow)
        self.assertIn("cargo publish --locked --no-verify", workflow)
        self.assertLess(workflow.index("Publish GitHub release"), workflow.index("publish-crate:"))
        self.assertLess(workflow.index("production-verification:"), workflow.index("package-crate:"))

    def test_build_matrix_action_inputs_are_not_duplicated_or_misplaced(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        build_binaries = workflow.split("  build-binaries:\n", 1)[1].split(
            "\n  production-bundle:\n", 1
        )[0]
        rust_step = build_binaries.split(
            "      - name: Install Rust toolchain\n", 1
        )[1].split("\n      - name:", 1)[0]
        python_step = build_binaries.split(
            "      - name: Install Python\n", 1
        )[1].split("\n      - name:", 1)[0]

        self.assertEqual(rust_step.count("\n        with:"), 1)
        self.assertIn("targets: ${{ matrix.target }}", rust_step)
        self.assertEqual(python_step.count("\n        with:"), 1)
        self.assertIn('python-version: "3.x"', python_step)
        self.assertNotIn("targets:", python_step)

    def test_registry_token_is_scoped_only_to_publish_step(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        publish_crate = workflow.split("  publish-crate:\n", 1)[1]
        publish_step = publish_crate.split(
            "      - name: Publish verified crate after GitHub release\n", 1
        )[1]

        self.assertNotIn(
            "    env:\n      CARGO_REGISTRY_TOKEN:", publish_crate.split(
                "      - name: Publish verified crate after GitHub release\n", 1
            )[0]
        )
        self.assertIn(
            "        env:\n          CARGO_REGISTRY_TOKEN: ${{ secrets.CARGO_REGISTRY_TOKEN }}",
            publish_step,
        )
        self.assertEqual(
            workflow.count("CARGO_REGISTRY_TOKEN: ${{ secrets.CARGO_REGISTRY_TOKEN }}"),
            1,
        )

    def test_crate_package_excludes_mutable_assets(self):
        cargo = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
        self.assertIn('include = [', cargo)
        self.assertIn('"src/**"', cargo)
        self.assertNotIn('"*.db"', cargo)
        self.assertNotIn('"model-cache/**"', cargo)

    def test_release_metadata_is_frozen_before_gate(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        notes = (ROOT / "docs/releases/0.4.0.md").read_text(encoding="utf-8")
        self.assertIn("finalized before the\nrelease gate", readme)
        self.assertIn("only `release-gate.json` and the release-gate summary", notes)
        self.assertIn("release-gate.json", readme)

    def test_release_publishes_windows_binary_and_installer(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("x86_64-pc-windows-msvc", workflow)
        self.assertIn("askman-windows-x86_64", workflow)
        self.assertIn("binary_name: askman.exe", workflow)
        self.assertIn("cp install.sh release-assets/install.sh", workflow)
        self.assertIn("release-assets/install.sh", workflow)

    def test_release_uses_native_runtime_provisioning_and_post_build_verification(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("provision_onnxruntime.py", workflow)
        self.assertIn("runtime-provision.json", workflow)
        self.assertIn("--target aarch64-apple-darwin", workflow)
        self.assertNotIn("~/.cache/ort.pyke.io", workflow)
        self.assertIn("ORT_PREFER_DYNAMIC_LINK", workflow)
        self.assertIn("production-bundle:", workflow)
        self.assertIn("production-verification:", workflow)
        self.assertIn("verify_release_asset.py", workflow)
        self.assertIn("network_probe.py", workflow)
        self.assertIn("release-asset-manifest.json", workflow)
        self.assertIn("--bundle-report production-bundle/matching-bundle-provision.json", workflow)
        self.assertIn("runtime-report runtime-evidence/runtime-metadata.json", workflow)
        self.assertIn("--source-runtime-report runtime-evidence/source-runtime-metadata.json", workflow)
        self.assertIn("--runtime-provision-report runtime-evidence/runtime-provision.json", workflow)
        self.assertIn("Assemble immutable runtime evidence", workflow)
        self.assertIn("--extract-dir $extractDir", workflow)
        self.assertIn("New-NetFirewallRule -DisplayName $ruleName", workflow)
        self.assertIn("Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule", workflow)
        self.assertIn("-u LD_LIBRARY_PATH", workflow)
        self.assertIn("-u DYLD_LIBRARY_PATH", workflow)
        self.assertIn("-u ORT_LIB_LOCATION", workflow)
        self.assertIn("HOME=\"$runtime_home\"", workflow)
        self.assertIn("archive_runtime_environment", (ROOT / "scripts/verify_release_asset.py").read_text(encoding="utf-8"))
        self.assertIn("--require-release-binary", ROOT.joinpath(".github/workflows/ci.yml").read_text(encoding="utf-8"))
        self.assertIn("askman_lifecycle", ROOT.joinpath(".github/workflows/ci.yml").read_text(encoding="utf-8"))

    def test_windows_firewall_probe_uses_external_baseline_and_strict_state(self):
        windows_steps = (
            (
                "ci",
                CI_WORKFLOW.read_text(encoding="utf-8"),
                "      - name: Verify bundle and queries on Windows\n",
            ),
            (
                "release",
                WORKFLOW.read_text(encoding="utf-8"),
                "      - name: Verify exact asset with Windows program firewall and probe\n",
            ),
        )
        for name, workflow, marker in windows_steps:
            with self.subTest(workflow=name):
                step = workflow.split(marker, 1)[1].split("\n      - name:", 1)[0]
                self.assertIn("Get-Command python -CommandType Application", step)
                self.assertIn("https://github.com/", step)
                self.assertIn("$baselineExitCode", step)
                self.assertIn("$blockedExitCode", step)
                self.assertIn("[guid]::NewGuid().ToString('D')", step)
                self.assertIn("Remove-Item -LiteralPath $probeState", step)
                self.assertIn("--baseline-succeeded", step)
                self.assertIn("--nonce $probeNonce", step)
                self.assertIn("--expected-url $externalUrl", step)
                self.assertIn("--expected-nonce $probeNonce", step)
                self.assertIn("Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule", step)
                self.assertIn("$rule.Direction", step)
                self.assertIn("$rule.Action", step)
                self.assertIn("$rule.Enabled", step)
                self.assertIn(".Program", step)
                self.assertIn("$filters[0].Program", step)
                self.assertIn("function Remove-FirewallRuleStrict", step)
                self.assertIn("Remove-NetFirewallRule -DisplayName $DisplayName -ErrorAction Stop", step)
                self.assertIn("Get-NetFirewallRule -ErrorAction Stop | Where-Object", step)
                self.assertIn("$cleanupFailures += Remove-FirewallRuleStrict", step)
                self.assertNotIn("Remove-NetFirewallRule -DisplayName $probeRuleName -ErrorAction SilentlyContinue", step)
                self.assertNotIn("Start-Process python", step)
                self.assertNotIn("127.0.0.1", step)

        probe_source = (ROOT / "scripts/network_probe.py").read_text(encoding="utf-8")
        for field in (
            "mode",
            "url",
            "nonce",
            "baseline_succeeded",
            "denied",
            "accepted",
            "connections",
            "error_classification",
        ):
            self.assertIn(f'"{field}"', probe_source)
        ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertGreaterEqual(ci_workflow.count("python scripts/network_probe.py server --state"), 2)
        self.assertIn("sandbox-exec -p '(version 1) (allow default) (deny network*)'", ci_workflow)
        self.assertIn("ASKMAN_CI_NETWORK_PROBE_NONCE", ci_workflow)
        self.assertIn("--network-probe-nonce $probeNonce", WORKFLOW.read_text(encoding="utf-8"))

    def test_ci_reproducibility_documents_platform_network_probe_contract(self):
        documentation = (ROOT / "docs/reproducibility/ci.md").read_text(encoding="utf-8")
        self.assertIn("Windows uses an external HTTPS baseline", documentation)
        self.assertIn("Linux and macOS keep the local TCP probe", documentation)
        self.assertIn("windows-firewall", documentation)
        self.assertIn("per-step nonce", documentation)

    def test_ci_macos_linker_header_padding_precedes_matrix_builds(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        marker = "      - name: Configure macOS linker header padding\n"
        self.assertEqual(workflow.count(marker), 1)
        step = workflow.split(marker, 1)[1].split("\n      - name:", 1)[0]
        self.assertIn("if: runner.os == 'macOS'", step)
        self.assertIn("-C link-arg=-Wl,-headerpad_max_install_names", step)
        self.assertIn('"$GITHUB_ENV"', step)
        verify_job = workflow.split("  verify:\n", 1)[1]
        self.assertLess(
            verify_job.index(marker), verify_job.index("cargo build --locked --features dev")
        )

    def test_release_macos_linker_header_padding_precedes_all_cargo_builds(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        marker = "      - name: Configure macOS linker header padding\n"
        self.assertEqual(workflow.count(marker), 2)
        for job_name, next_job in (
            ("  build-binaries:\n", "\n  production-bundle:\n"),
            ("  production-bundle:\n", "\n  production-verification:\n"),
        ):
            job = workflow.split(job_name, 1)[1].split(next_job, 1)[0]
            self.assertEqual(job.count(marker), 1)
            step = job.split(marker, 1)[1].split("\n      - name:", 1)[0]
            self.assertIn("if: runner.os == 'macOS'", step)
            self.assertIn("-C link-arg=-Wl,-headerpad_max_install_names", step)
            self.assertIn('"$GITHUB_ENV"', step)
            self.assertLess(job.index(marker), job.index("cargo build"))

    def test_windows_ci_stages_verified_runtime_before_execution(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        marker = "      - name: Stage pinned Windows runtime beside built binaries\n"
        self.assertEqual(workflow.count(marker), 1)
        verify_job = workflow.split("  verify:\n", 1)[1]
        step = verify_job.split(marker, 1)[1].split("\n      - name:", 1)[0]
        self.assertIn("if: runner.os == 'Windows'", step)
        self.assertIn("shell: pwsh", step)
        self.assertIn("ASKMAN_ORT_RUNTIME_ROOT", step)
        self.assertIn("runtime-provision.json", step)
        self.assertIn("Get-FileHash", step)
        self.assertIn("target/debug/deps", step)
        self.assertIn("target/release/deps", step)
        self.assertGreater(
            verify_job.index(marker), verify_job.index("Build release-mode lifecycle test CLI")
        )
        self.assertLess(
            verify_job.index(marker), verify_job.index("Run Rust tests and lifecycle coverage")
        )
        self.assertLess(
            verify_job.index(marker),
            verify_job.index("Provision pinned bundle assets (networked setup)"),
        )


if __name__ == "__main__":
    unittest.main()
