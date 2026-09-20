# Main versus retrieval-v2 release gate

Issue #33 provides `scripts/run_release_gate.py`. It builds the `main` and
candidate `askman` binaries separately with `--locked --offline`, stages the
candidate matching bundle, and runs both CLIs on identical frozen
`evaluation-v2-expanded` development and holdout tasks. This is the versioned
corpus-backed release freeze from issue #39.

Provision the main release data directory and a validated candidate bundle
before running the gate. The main directory must contain `commands.db` and its
pinned model cache. Provisioning/download is intentionally outside the gate;
the gate records SHA-256 input digests and does not mutate the supplied main
directory or bundle. The runner rejects any evaluation manifest or split whose
digest differs from the checked-in expanded freeze.

```sh
python3 scripts/run_release_gate.py \
  --main-ref main \
  --candidate-ref origin/retrieval-v2 \
  --main-data-dir /path/to/main-data \
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

The primary outcome is user-visible `Success@1`; `Success@3`, coverage,
incorrect-answer counts, false-answer counts, platform/family breakdowns, and
internal candidate details are secondary or diagnostic. The gate uses a fixed
seed and 10,000 paired bootstrap resamples over answerable tasks, requires a
five-point overall `Success@1` gain, positive gains in two families, no safety
regression, and no more than 20% warmed-query p95 or peak-memory regression.
Per the ADR-0001 amendment (2026-09-20, pre-registered before holdout access),
the bootstrap condition is a one-sided 95% lower bound above zero; the
two-sided interval is still reported and a two-sided interval containing zero
still produces an **inconclusive** recommendation.

Release publication requires a checked-in machine-readable report at
`docs/reproducibility/artifacts/release-gate.json` with
`recommendation: "better_askman"`, a passing `gate`, the frozen manifest
digest, clean execution records, and an approved Linux or macOS query-time
network wrapper. The tag workflow validates that report against the tagged
candidate commit before building or publishing any release assets. No report
is checked in until the authorized main-data and matching-bundle inputs are
available.

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
