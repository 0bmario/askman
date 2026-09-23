# Main versus retrieval-v2 release gate

Issue #33 provides `scripts/run_release_gate.py`. It builds the `main` and
candidate `askman` binaries separately with `--locked --offline`, stages the
candidate matching bundle, and runs both CLIs on identical frozen
`evaluation-v2-expanded` development and holdout tasks. This is the versioned
corpus-backed release freeze from issue #39.

The release report uses schema 2. It records `evaluated_candidate_commit`, the
commit whose candidate binary was measured. The release tag must descend from
that commit, and the final tree may differ only in
`docs/reproducibility/artifacts/release-gate.json` and this summary document.
This lets the evidence be committed after evaluation without making the report
depend on the hash of the commit that contains it.
Freeze source and release metadata before the run. Then commit only the passing
evidence JSON and this summary, and tag that evidence commit.

Provision the main release data directory and a validated candidate bundle
before running the gate. The main directory must contain `commands.db` and its
pinned model cache. Provisioning/download is intentionally outside the gate;
the gate records SHA-256 input digests and does not mutate the supplied main
directory or bundle. The runner rejects any evaluation manifest or split whose
digest differs from the checked-in expanded freeze.

```sh
cargo fetch --locked
RUN_DIR="$(mktemp -d)"
scripts/smoke_offline.sh provision "$RUN_DIR"

# macOS: use the provisioned ONNX Runtime 1.20.0 for both gate builds.
export DENSE_ORT="$RUN_DIR/onnxruntime/onnxruntime-osx-arm64-1.20.0"
export DYLD_LIBRARY_PATH="$DENSE_ORT/lib"
export LIBONNXRUNTIME_NO_PKG_CONFIG=1
export ORT_LIB_LOCATION="$DENSE_ORT"
export ORT_PREFER_DYNAMIC_LINK=1

python3 scripts/run_release_gate.py \
  --main-ref main \
  --candidate-ref origin/retrieval-v2 \
  --main-data-dir "$RUN_DIR/data" \
  --bundle /path/to/matching-bundle \
  --allow-holdout \
  --output-json /tmp/askman-release-gate.json \
  --output-markdown /tmp/askman-release-gate.md
```

The query phase uses `sandbox-exec` with `deny network*` on macOS and
`unshare --net` on Linux. It captures each binary's commit, lockfile digest,
binary digest, bundle/data digests, runtime metadata, exit status, displayed
example IDs, abstentions, and failure examples. Output is scored by stable
example ID, not command name alone. Any non-zero exit status or timeout makes
the recommendation inconclusive. `common` tasks intentionally use the
shipping CLI default (common pages plus the host target); all runs in one gate
share the same host.

On macOS, provision and use ONNX Runtime `1.20.0` from
`scripts/smoke_offline.sh provision`; do not substitute a host-installed
runtime. The archive and shared library are SHA-256 checked by that harness.
The explicit path is required because a newer Homebrew runtime can abort during
process teardown. See [dense retrieval](dense-retrieval.md#build) for the
runtime environment details. The report records each binary's rpath, and the
release validator requires both macOS builds to point into the provisioned
`onnxruntime-osx-arm64-1.20.0/lib` directory.

The primary outcome is user-visible `Success@1`; `Success@3`, coverage,
incorrect-answer counts, false-answer counts, platform/family breakdowns, and
internal candidate details are secondary or diagnostic. The gate uses a fixed
seed and 10,000 paired bootstrap resamples over answerable tasks, requires a
five-point overall `Success@1` gain, positive gains in two families, no safety
regression, and no more than 20% warmed-query p95 or peak-memory regression.
Per the ADR-0001 amendment (2026-09-20, pre-registered before holdout access),
the bootstrap condition is the one-sided 95% lower bound (the empirical 5th
percentile) above zero. The two-sided 95% interval remains a diagnostic; it
may contain zero while the one-sided condition passes.

Release publication requires a checked-in machine-readable report at
`docs/reproducibility/artifacts/release-gate.json` with
`recommendation: "better_askman"`, a passing `gate`, the frozen manifest
digest, clean execution records, and an approved Linux or macOS query-time
network wrapper. The tag workflow validates the evaluated candidate as an
ancestor of the tagged release commit and restricts post-evaluation changes to
the evidence JSON and this summary before building or publishing assets. No
report is checked in until the authorized main-data and matching-bundle inputs
are available.

Fresh-process measurements cover every benchmark task. Warmed-query samples
warm filesystem/model caches first, then run fresh CLI processes; this is the
strongest measurement available without a persistent query-server mode in the
shipping CLIs, and the limitation is recorded in the machine report.

## Recorded run (2026-09-20): inconclusive

The first complete paired run: `main` @ `8bd9fa2` versus `retrieval-v2` @
`8b19997`, both splits, sandboxed query phase, zero execution failures.
Machine-readable report:
[`artifacts/release-gate-comparison-v1.json`](artifacts/release-gate-comparison-v1.json)
(kept off the publication path above because the recommendation is not
`better_askman`).

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 (combined) | 37/60 | 45/60 (+13.3pp) |
| Success@3 (combined) | 48/60 | 52/60 |
| Incorrect answered | 10/58 | 4/56 |
| False answers | 7/60 | 0/60 |
| Warmed p95 / peak memory | 93.5 ms / 237.9 MB | 107.9 ms / 331.7 MB |

- Bootstrap (seed `33031`): two-sided 95% **[+3.3pp, +25pp]** — excludes zero;
  one-sided 95% lower bound +3.3pp — **passes** the amended condition.
- Latency +15.4% — inside the 20% allowance.
- **Family regression**: `holdout39-osx-speech-phrase` (main 5/5, candidate
  4/5) — on `holdout-v2r1-holdoutosx-speech-04` ("use macOS say to speak
  text") the candidate displayed the `say --output-file` variant at rank 1
  with the weak-match cutoff retaining one result.
- **Peak memory +39.4%**: the candidate's user-defined embedding path holds
  the 90 MB `model.onnx` bytes in Rust memory while the ONNX session keeps
  its own copy; main's named-model path does not.

Recommendation: **inconclusive**. Both gaps are product work (behavior-variant
ranking for same-command pages; releasing the duplicate model buffer after
session creation) and are queued as retrieval/bundle follow-ups.

## Recorded run (2026-09-21): inconclusive

Second full paired run: `main` @
`8bd9fa296ea7e2f461202091f2ade47221bc8a0e` versus `retrieval-v2` @
`b3ebb12f9ef6208eac541aa7f4ad48001f07957e`; both splits, sandboxed query
phase, zero execution failures. Both builds used the provisioned ONNX Runtime
1.20.0 for macOS arm64. Machine-readable report:
[`artifacts/release-gate-comparison-v2.json`](artifacts/release-gate-comparison-v2.json)
(kept off the publication path because the recommendation is not
`better_askman`).

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 (combined) | 37/60 | 52/60 (+25pp) |
| Success@3 (combined) | 48/60 | 52/60 |
| Incorrect answered | 10/58 | 4/56 |
| False answers | 7/60 | 0/60 |
| Warmed p95 / peak memory | 86.8 ms / 235.9 MB | 91.1 ms / 241.8 MB |

- Bootstrap (seed `33031`, 10,000 paired resamples): two-sided 95% interval
  **[+13.3pp, +36.7pp]** — excludes zero.
- Warmed p95 latency +5.0% and peak memory +2.5% — both inside the 20% limit.
- **Sole family regression**: `holdout39-osx-speech-phrase` (main 5/5,
  candidate 4/5); task `holdout-v2r1-holdoutosx-speech-04` ("use macOS say to
  speak text") ranked the `say --output-file` variant first.

Recommendation: **inconclusive**. The holdout speech-family Success@1
regression is the sole recorded gate failure.
