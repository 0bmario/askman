# Cross-platform CI and offline verification

Issue #34 runs the native Rust build, Rust and Python tests, frozen release
benchmark validation, bundle validation, lifecycle tests, and disposable
offline queries on Ubuntu, macOS, and Windows GitHub runners.

The CI job has two explicit phases:

1. `cargo fetch --locked`, native runtime priming, and pinned model downloads
   are the only networked setup steps.
2. Formatting, compilation, tests, bundle build/validation, and queries use
   already-fetched dependencies and local assets. The bundle and model cache
   live below the runner's temporary directory; user data and release assets
   are never read or changed.

The verifier is `scripts/ci_offline.py`. It downloads the five model files at
the revision and SHA-256 values already pinned in `src/dense.rs`, builds a
matching bundle from the checked-in full-corpus fixture, validates the complete
bundle, and queries the candidate under all four logical target policies:
`common`, `linux`, `osx`, and `windows`. Its `prepare` phase also serves the
generated release assets from a loopback-only HTTP server and runs the shipping
CLI's real `setup` and `update` commands before stopping that server.
`common` follows the shipping CLI default (common pages plus the host target),
matching the release-gate protocol.

The lifecycle tests use the production `BundleStore` state machine with
synthetic manifest records so they can run before a public release exists.
They cover first-use activation, explicit update, rollback, failed validation,
partial state recovery, and immutable IDs. The release workflow must still run
the live GitHub download path after the first compatible release assets exist.

The loopback lifecycle run additionally verifies clean setup, a truncated
update archive, preservation of the active state after that failure, and a
successful explicit update. The development-only `ASKMAN_RELEASE_BASE_URL`
override is used only for this disposable local server; normal builds keep the
fixed GitHub release endpoint.

Each matrix job uploads:

- `bundle-manifest.json` with the immutable bundle ID and component digests;
- `release-benchmark-inputs.json` with frozen input paths and SHA-256 values;
- `runtime-metadata.json` with commits, tool versions, host data, network
  policy, and bundle digests;
- command logs and per-policy query output digests.

## Reproduce locally

From a checkout with Cargo dependencies available:

```sh
cargo fetch --locked
cargo fmt --all -- --check
cargo check --locked --offline --all-targets --features dev
cargo build --locked --offline --release --bin askman
cargo test --locked --offline --all-targets --features dev
python -m unittest discover -s tests -p 'test_*.py'
python scripts/validate_evaluation_v2.py \
  --manifest tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json
bash tests/smoke_offline.sh
python scripts/ci_offline.py provision \
  --work-dir /tmp/askman-ci-work \
  --report-dir /tmp/askman-ci-report
python scripts/ci_offline.py prepare \
  --work-dir /tmp/askman-ci-work \
  --report-dir /tmp/askman-ci-report
python scripts/ci_offline.py verify \
  --work-dir /tmp/askman-ci-work \
  --report-dir /tmp/askman-ci-report
```

For a real network-denied verification, run the `verify` phase inside the
platform's network sandbox after provisioning. Linux uses temporary root
firewall rules (`iptables`/`ip6tables`) that reject non-loopback egress; the
macOS developer smoke harness uses `sandbox-exec`. The full release gate still
requires separately provisioned `main` data and an authorized matching bundle;
those inputs are intentionally not checked in or downloaded by this CI job.

The matrix sets `LIBONNXRUNTIME_NO_PKG_CONFIG=1` and
`ORT_PREFER_DYNAMIC_LINK=1`, so a host-installed ONNX Runtime cannot replace
the build's pinned runtime. The setup phase primes the Rust debug binaries
before the network sandbox is entered; the verifier then rebuilds or reuses
them with `--offline`.

The hosted Windows runner has no supported network namespace equivalent in
this workflow. Its job still uses `--offline`, a local validated bundle, and
the lifecycle test that proves active-bundle lookup does not contact its
release URL. A Windows host with an outbound firewall or equivalent isolation
is required for an OS-enforced network-denial claim.
