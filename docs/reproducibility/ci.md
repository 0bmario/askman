# Cross-platform CI and offline verification

Normal pushes and pull requests run one cached Ubuntu job with formatting,
Rust/Python tests, frozen benchmark validation, and portable smoke checks.
The job provisions the pinned ONNX Runtime into a runner-temporary directory
before switching Cargo offline and caches only Cargo/build outputs under an
OS/architecture key.
The release workflow calls this reusable workflow with `full: true` to run the
native Rust build, bundle validation, lifecycle tests, and disposable offline
queries on Ubuntu, macOS, and Windows GitHub runners.

Manual dispatch defaults to the full release verification. The full mode is
the required cross-platform release gate; the fast mode deliberately does not
download the ONNX model or build a matching bundle.

Full mode has two explicit phases:

1. `cargo fetch --locked`, native runtime priming, and pinned model downloads
   are the only networked setup steps.
2. Formatting, compilation, tests, bundle build/validation, and queries use
   already-fetched dependencies and local assets. The bundle and model cache
   live below the runner's temporary directory; user data and release assets
   are never read or changed.

The full verifier is `scripts/ci_offline.py`. It downloads the five model files at
the revision and SHA-256 values already pinned in `src/dense.rs`, builds two
genuinely distinct valid matching bundles from the checked-in full-corpus
fixture, validates both complete bundles, and queries the shipping release
binary under all four logical target policies:
`common`, `linux`, `osx`, and `windows`. Its `prepare` phase also serves the
generated release assets from a loopback-only HTTP server and runs a
release-mode dev/test CLI's `setup` and `update` commands before stopping that
server. Its post-build query phase invokes the independently preserved exact
shipping release binary with structured JSON output and asserts the expected
top platform and source path for all four policies; a non-empty human-readable
response is not sufficient.
`common` follows the shipping CLI default (common pages plus the host target),
matching the release-gate protocol.

The public `-j/--json` output remains the historical object with `query` and
`results`. CI uses hidden `--ci-json-v1`, an explicit versioned array contract,
so release probes do not change existing consumers.

The lifecycle tests use the production `BundleStore` state machine with
synthetic manifest records so they can run before a public release exists.
They cover first-use activation, explicit update between two immutable IDs,
rollback, failed validation, partial state recovery, and immutable IDs. The
publication suite also runs two separate processes against one store to prove
same-ID publication cannot replace an already validated directory. The
release workflow must still run the live GitHub download path after the first
compatible release assets exist.

The loopback lifecycle run additionally verifies clean setup, successful
offline queries after setup/update/rollback (the query process is pointed at
an unreachable release endpoint), and preservation of the active and
previous bundles after partial, checksum-invalid, mixed, and incompatible
downloads. The failure archives are deterministic local fixtures. The
development-only `ASKMAN_RELEASE_BASE_URL` override is used only for this
disposable local server; normal builds keep the fixed GitHub release endpoint.

The release workflow's `production-bundle` job is separate from the matrix CI:
it runs on canonical Darwin/arm64, downloads and verifies the pinned
tldr-pages, model, and ONNX Runtime inputs, invokes
`scripts/provision_tldr_bundle.py` without `--allow-dirty`, and fails closed on
ineligible evidence or mismatched detached manifest/archive assets. The
validated `matching-bundle-manifest.json` and `matching-bundle.tar.gz` are
published with the CLI assets for the `v0.4.0` release.

The `package-crate` job then packages `askman-0.4.0`, verifies its archive and
member digests, rejects database/model/cache/runtime assets, and installs the
extracted crate to smoke-test `askman --version`. The crates.io publication job
depends only on the successful GitHub release job, so `CARGO_REGISTRY_TOKEN` is
not used until the GitHub binaries and matching bundle are already published.

Before publication, `production-verification` downloads the exact binary
artifact and this exact production bundle on every native matrix runner. It
extracts the archive, verifies binary/runtime/license digests and loader
linkage, then runs the extracted shipping binary against the staged bundle for
all four policies. Tampered-state and rollback-without-previous checks must
fail closed. The archive uploaded by `build-binaries` is the byte sequence
tested by this job; publication verifies its SHA-256 again. Every archive
contains the pinned ONNX Runtime library beside the executable and its license
notices, with `$ORIGIN`, `@loader_path`, or DLL-side-by-side resolution.

Each full-mode matrix job uploads:

- `bundle-manifest.json` with the immutable bundle ID and component digests;
- `release-benchmark-inputs.json` with frozen input paths and SHA-256 values;
- `runtime-metadata.json` with commits, tool versions, host data, native
  ONNX Runtime resolution/version/path/linkage/library SHA-256, shipping
  binary SHA-256, network policy, and bundle digests;
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
# Run `verify` through an OS network-isolation wrapper; an unwrapped call
# fails closed and must not be labeled offline evidence.
```

For a real network-denied verification, run the `verify` phase inside the
platform's network sandbox after provisioning. Linux uses temporary root
firewall rules (`iptables`/`ip6tables`) that reject all outbound traffic;
macOS requires `sandbox-exec` with `deny network*`; Windows requires a
program-specific outbound `NetFirewallRule` for the exact release binary.
Each native release verification also starts a local TCP server, attempts a
connection under the isolation boundary, records zero accepted connections,
and validates the installed rule/sandbox. Rule installation, probe validation,
and cleanup are fail-closed: if isolation cannot be established, the job fails
and produces no passing evidence. The full release gate still requires
separately provisioned `main` data and an authorized matching bundle; those
inputs are intentionally not checked in or downloaded by this CI job.

The full matrix sets `LIBONNXRUNTIME_NO_PKG_CONFIG=1` and
`ORT_PREFER_DYNAMIC_LINK=1`, so a host-installed ONNX Runtime cannot replace
the build's pinned runtime. The setup phase primes the Rust debug binaries
before the network sandbox is entered; the verifier then rebuilds or reuses
them with `--offline`. Cargo and pinned model assets are cached by runner and
content revision; cache hits are still checked by the existing hash and
manifest validation.

Each child command in the lifecycle and offline-verification phases has a
five-minute timeout. Linux additionally wraps each multi-command phase,
including firewall rule acquisition and cleanup, in a ten-minute outer
timeout. Subprocess output is streamed into the report while it runs, so a
timeout identifies the last phase reached. Linux runs the dense
lifecycle/query processes with `OMP_NUM_THREADS=1` and one CPU in their
inherited affinity mask; this makes `available_parallelism()` deterministic
without changing the assertions or bundle inputs. Linux firewall rule
insertion waits at most ten seconds for the xtables lock and fails closed if
isolation cannot be established; cleanup uses the same bounded wait. These
bounds turn runner lock or teardown hangs into actionable CI failures without
allowing an unisolated query run to pass.

The matrix records `runtime-metadata.json` for every OS. It includes the native
runtime resolution source, version, library path and SHA-256, binary linkage,
and shipping-binary SHA-256. Release binary jobs provision the pinned
ONNX Runtime 1.20.0 Microsoft archive into a runner-temporary directory and
record its archive, library, and license/notice digests in
`runtime-provision.json`; no `ort-sys` download cache is used as a runtime
input. The Rust build cache is scoped by OS/architecture and lockfile. The
macOS paths are patched for every executed development tool. The Windows job
publishes `askman-windows-x86_64` beside the Linux and macOS archives.
