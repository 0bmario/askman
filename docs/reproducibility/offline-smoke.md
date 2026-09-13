# Offline retrieval smoke run

This is a macOS ARM64 developer verification for the current Askman retrieval path. It
does not change the installed database or model cache, and it is separate from
the future corpus and evaluation pipelines.

## What is fixed

The provisioning step downloads and verifies:

- `commands.db` from the v0.3.3 release, SHA256
  `0218c1fd18dc6eb1c6b405356c92e47379286cec68f9fea1a70be896d5f71495`.
- `Qdrant/all-MiniLM-L6-v2-onnx` at revision
  `5f1b8cd78bc4fb444dd171e59b18f3a3af89a079`.
- ONNX Runtime `1.20.0` from the Microsoft release archive,
  SHA256 `2bcfaafa9ff0a3a94f78e3af2f135ffde5bb2d79b08e83a50dbc450b0d20ddae`.

The model files are individually checked before they are placed in the
fastembed cache layout. The database and model are the public artifacts used
by the current release; no generated binary, database or model file belongs in
the repository.

## Reproduce

Requirements: macOS ARM64, Rust/Cargo, Xcode command-line tools, Python 3,
and curl. Other hosts are rejected until their runtime and network isolation
have been pinned and verified.

Run from the repository root. Fetch Cargo dependencies and provision assets
while online; the subsequent build and queries run with networking denied:

```sh
cargo fetch --locked
RUN_DIR="$(mktemp -d)"
scripts/smoke_offline.sh provision "$RUN_DIR"
scripts/smoke_offline.sh run "$RUN_DIR"
```

The script builds an isolated `$RUN_DIR/target/release/askman` with `cargo
build --locked --offline`. It pins the official ONNX Runtime 1.20.0 archive,
forcing the build away from any pkg-config runtime on the host. The build,
socket probe and Askman run under `sandbox-exec` with `deny network*`; even
native build scripts cannot download missing dependencies. If dependencies
are missing, fetch them explicitly before retrying. The query phase uses an
explicit `ASKMAN_DATA_DIR` and the staged `HF_HOME`. Color is disabled for
stable assertions. This harness always builds the checked-out source.

The run directory contains:

- `run-manifest.txt`: revision, lockfile and asset digests, runtime/linkage and
  host information, and inference settings. The thread policy is recorded;
  the effective ORT thread count is not instrumented.
- `offline-smoke.tsv`: the exact fixture snapshot used, with its SHA256 and
  the committed fixture SHA256 recorded separately in the manifest. A mismatch
  identifies a local fixture change.
- `network-probe.txt`: the OS-level denial result.
- `smoke-output.txt` and `results/query-*.txt`: the fixture inputs, expected
  command names, complete CLI output and process exit status.

The fixture in `tests/fixtures/offline-smoke.tsv` checks the first result and
a specific example under that result for `mv`, `ls`, and `grep`, using Linux
platform filtering on the macOS host. These are regression probes, not
held-out evaluation tasks; do not reuse them as quality evidence.

Run `bash tests/smoke_offline.sh` for asset-reference and output-validation
checks without downloading assets or initializing the model.

## Interpretation

The run is successful only when the network probe reports a
blocked socket (`EPERM` or `EACCES`), every query returns its expected top
command and example, and every process exits with status zero. A nonzero
status is preserved and the corresponding
output is left in the run directory, including native-runtime warnings or
aborts. Asset digests are checked again at run time before any query starts.

The smoke run establishes reproducibility on the named host and verifies that
the provisioned query does not need the network. It does not prove that every
released binary, operating system, CPU or future model/runtime combination
has the same teardown behavior. It also does not measure retrieval quality or
performance.

On the tested macOS ARM64 host, the original build selected Homebrew ONNX
Runtime 1.22.0 through pkg-config. It returned retrieval output, emitted
duplicate ONNX schema warnings, and aborted with `mutex lock failed: Invalid
argument` (status 134). A standalone native probe reproduced that abort when
the ORT environment was retained through process teardown; explicitly
releasing it exited cleanly. The Askman smoke run with the pinned ORT 1.20.0
runtime exits cleanly without the warnings. This records the observed runtime
boundary without claiming that duplicate schema warnings alone establish the
cause.
