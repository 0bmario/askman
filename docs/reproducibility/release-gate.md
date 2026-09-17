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
A 95% interval that contains zero produces an **inconclusive** recommendation.

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
