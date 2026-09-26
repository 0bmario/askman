# Main versus retrieval-v2 release gate

Issue #33 provides `scripts/run_release_gate.py`. It builds the `main` and
candidate `askman` binaries separately with `--locked --offline`, stages the
candidate matching bundle, and runs both CLIs on identical frozen
`evaluation-v2-expanded` tasks. Use `--candidate-working-tree` to build the
current checkout, including uncommitted changes. This is the versioned
corpus-backed release freeze from issue #39.

Provision the main release data directory and a validated candidate bundle
before running the gate. The main directory must contain `commands.db` and its
pinned model cache. Provisioning/download is intentionally outside the gate;
the gate records SHA-256 input digests and does not mutate the supplied main
directory or bundle. Before querying, it requires equal visible-corpus
inventories after stripping `More information:` links, normalizing page
description whitespace, and case-folding Windows page command names (Windows
PowerShell commands are case-insensitive). It verifies every model asset
against the bundle manifest. The report records the shared
inventory digest, candidate source digest, and verified model-asset count. The
schema-4 report also records the gate-runner digest. The runner rejects any
evaluation manifest or split whose digest differs
from the checked-in expanded freeze.

The consumed evaluation-v2 holdout remains available only as historical
evidence. For a new independent run, pass
`--independent-holdout-manifest tests/fixtures/evaluation/fresh-holdout-v1.manifest.json`.
The runner requires `--allow-holdout`, verifies the pinned freeze and dataset
digests, and evaluates holdout quality separately from development. A release
recommendation requires holdout Success@1 improvement with a positive
one-sided paired-bootstrap lower bound, no holdout safety or platform losses,
successful network-denied execution, and resource limits met in every measured
phase.
`--dev-only` does not load either holdout dataset.

The frozen evaluation-v2 labels use parser v3. If a candidate bundle uses a
new parser version, the gate rebuilds the frozen 24-page source with the pinned
parser-v3 reference, then compares stable example IDs, page IDs, platforms,
commands, and visible descriptions against the candidate. A mismatch fails
before query evaluation. The original v3 manifest and frozen task files remain
unchanged; the candidate build uses a separate versioned manifest.

Release runs require the evaluation baseline `commands.db` SHA-256
`ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db`. It was
reproduced by the `main` importer at `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
from the frozen 24-page `e1cb966e711d73c42d75e79834be7e4dc17264ef` corpus with
the pinned model assets. This pins the baseline vectors, not only visible text.
The full installed v0.3.3 DB documented in [`offline-smoke.md`](offline-smoke.md)
is a different corpus and is not a valid input for this 142-example benchmark.
`--dev-only` may use another scratch database; it records that DB as unpinned,
and the release-readiness validator rejects it as promotion evidence.

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

Use `--dev-only` for development verification only. It cannot produce a
release decision: its recommendation is always inconclusive, and its protocol
metadata marks the development-and-holdout requirement as unmet.

Build a candidate bundle from the versioned parser-v4 manifest with the pinned
model cache provisioned by `scripts/smoke_offline.sh`:

```sh
cargo run --locked --offline --features dev --bin tldr_subset -- bundle-build \
  --manifest tests/fixtures/tldr-evaluation-v2/manifest-v4.json \
  --snapshot tests/fixtures/tldr-evaluation-v2 \
  --model-cache /path/to/provisioned-data/models \
  --output /tmp/askman-matching-bundle \
  --cli-compatibility askman=0.3.3 \
  --dense-recipe main-compatible
```

## Current focused candidate — development only

The candidate uses main-compatible embedding text, `focused-v1` source-backed
query mappings, raw cosine ranking, distance `<= 0.55`, early
one-example-per-page selection, and scoped abstention for negated or
unsupported file-to-stdout requests. On the identical pinned dev records, the
paired gate measured:

| Metric | main | focused candidate |
| --- | ---: | ---: |
| Success@1 | 18/30 | 30/30 |
| Success@3 | 23/30 | 30/30 |
| False answers | 1/30 | 0/30 |
| Warm p95 | 86.343 ms | 85.001 ms |
| Warm peak memory | 236,077,752 B | 236,536,504 B |
| Fresh p95 | 89.266 ms | 85.653 ms |
| Fresh peak memory | 236,438,200 B | 282,936,040 B |

There were zero execution failures under the network-denied wrapper. The
candidate improved Success@1 on every platform and tied or improved
Success@3. Every measured fresh and warm resource metric stayed within the 20%
ceiling. The fresh memory increase is 19.7%. Source digest is
`ac58a8c3c63390b31f0af599be4939be49e87510e28282be6d8a6c276164dfa2`; binary
digest is
`2e03c4d99601b9d14f1dc0ad63545c12b274ddc5356abbaa043d8b914ce80521`. These
are dev-only results. The gate measured 30/30 vs main's 18/30 Success@1,
30/30 vs 23/30 Success@3, and zero vs one false answers; platform Success@1
improved in all four groups. Earlier focused timing runs remain recorded. The
new holdout is frozen and unscored pending explicit authorization. Reports:
[`latest focused dev-only gate`](artifacts/main-vs-retrieval-v2-focused-dev-only-v5.json),
[`previous focused dev-only gate`](artifacts/main-vs-retrieval-v2-focused-dev-only-v4.json),
[`earlier focused dev-only gate`](artifacts/main-vs-retrieval-v2-focused-dev-only-v3.json),
[`focused controlled ablation`](artifacts/retrieval-v2-controlled-ablation-dev-v2.json).

After authorization, the independent command uses the frozen dev dataset and
the fresh holdout manifest:

```sh
python3 scripts/run_release_gate.py \
  --candidate-ref 3494a11c57c31045bb9897c9fa187d768e18ebcb \
  --main-data-dir /path/to/main-data \
  --bundle /path/to/matching-bundle \
  --allow-holdout \
  --independent-holdout-manifest tests/fixtures/evaluation/fresh-holdout-v1.manifest.json \
  --holdout-dataset tests/fixtures/evaluation/fresh-holdout-v1.json \
  --output-json /tmp/askman-fresh-holdout-gate.json \
  --output-markdown /tmp/askman-fresh-holdout-gate.md
```

## Earlier broad-rule candidate (2026-09-26)

The earlier dev-only paired run used the exact
pinned main database and 142 equivalent parser-v3/v4 records. Main measured
18/30 Success@1, 23/30 Success@3, and 1/30 false answers; the dense-only
candidate measured 30/30, 30/30, and 0/30. Fresh p95 was 90.30 ms for main and
89.79 ms for candidate; peak memory was 238.2 MB and 245.3 MB. Warmed p95 was
88.38 ms and 92.39 ms; peak memory was 237.5 MB and 236.8 MB. All resource
measurements were inside the gate's 20% warmed-query limits. An earlier run
had substantially different memory and warmed-latency measurements, so both
reports are retained. The candidate source digest is
`419c2a86c559735bd62173885371bd78e67e4c4c8414eef01f05917813bf046d`; the
candidate binary digest remains
`bf3e293d6ecfee8f5d0bbbaafaac57b7498a8fc92adcb8865120b89ff6a077d9`. The
decision remains `inconclusive` because this run used dev tasks only. Reports:
[`latest paired dev-only gate`](artifacts/main-vs-retrieval-v2-dev-only-v2.json),
[`earlier paired dev-only gate`](artifacts/main-vs-retrieval-v2-dev-only-v1.json),
and [`controlled ablation`](artifacts/retrieval-v2-controlled-ablation-dev-v1.json).

## Prior authorized run (2026-09-26): broad candidate not promoted

After explicit authorization, one canonical run compared the frozen candidate
against the pinned main database and matching bundle on both splits. The
candidate source digest was `419c2a86c559735bd62173885371bd78e67e4c4c8414eef01f05917813bf046d`;
all 142 parser-v3/v4 records were equivalent. Main and candidate had no
execution failures under the network-denied query wrapper.

| Split | Metric | Main | Candidate |
| --- | --- | ---: | ---: |
| Dev | Success@1 | 18/30 | 30/30 |
| Dev | Success@3 | 23/30 | 30/30 |
| Dev | False answers | 1/30 | 0/30 |
| Holdout | Success@1 | 19/30 | 19/30 |
| Holdout | Success@3 | 25/30 | 20/30 |
| Holdout | False answers | 6/30 | 6/30 |
| Combined | Success@1 | 37/60 | 49/60 |
| Combined | Success@3 | 48/60 | 50/60 |
| Combined | False answers | 7/60 | 6/60 |

Holdout `Success@3` also fell on macOS (10/10 to 8/10) and Windows (4/5 to
1/5); holdout `Success@1` tied main on every platform. The runner's pooled
bootstrap reports a +20-point combined `Success@1` gain (95% interval
[+10pp, +30pp]), so its machine decision is `better_askman`. That pooled result
is driven by development gains and does not satisfy the independent
improvement/no-regression requirement. The candidate is **not approved**.

Warmed p95 was 91.64 ms for main and 88.56 ms for candidate; peak memory was
237,175,480 and 237,535,904 bytes. Both are within the 20% limits. False-answer
rate tied on holdout, and offline execution passed. Retrieval relevance is the
blocking regression.

Before this run, broad searches accidentally surfaced one frozen holdout row
and snippets from existing holdout evidence. They were not used for tuning;
the evaluation is not fully blind. No candidate changes were made after the
run. Retire this holdout from future candidate selection and obtain a fresh
unseen split before another independent claim.

The immutable run output is
[`main-vs-retrieval-v2-authorized-v1.json`](artifacts/main-vs-retrieval-v2-authorized-v1.json)
and its rendered report. It passes the structural readiness validator, which
does not decide the split-specific promotion condition above. Do not copy it to
the publication path.

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
regression, and no more than 20% regression in fresh-process p95 or peak memory
for each split, or warmed-query p95 or peak memory.
Per the ADR-0001 amendment (2026-09-20, pre-registered before holdout access),
the bootstrap condition is a one-sided 95% lower bound above zero; the
two-sided interval is still reported for transparency. A two-sided interval
containing zero does not by itself make the recommendation inconclusive.

Release publication requires a checked-in machine-readable report at
`docs/reproducibility/artifacts/release-gate.json` with
`recommendation: "better_askman"`, a passing `gate`, the frozen manifest
digest, clean execution records, and an approved Linux or macOS query-time
network wrapper. The tag workflow validates that report against the tagged
candidate commit before building or publishing any release assets. No report
is checked in until the authorized main-data and matching-bundle inputs are
available.

The machine `passed` flag and structural report validator are not sufficient
when development and holdout outcomes differ. Apply ADR-0001's split-specific
holdout conditions before promotion; the authorized v1 report is not approved.

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
