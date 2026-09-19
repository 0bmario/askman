# Hybrid retrieval comparison

Issue #19 adds a development-only hybrid candidate to the frozen retrieval
evaluation. It fuses the existing keyword and dense candidate IDs. The original
v1 fixture remains immutable historical evidence; the current candidate policy
is tuned separately against the expanded development split below.

## Frozen configuration

The checked-in configuration is
`tests/fixtures/evaluation/hybrid-config-v1.json`.

- config SHA256: `1059c9bf72e570cf431ccddb2676176bac65238b5c4c8a07b63891e5133a9c7f`
- dataset: `askman-evaluation-v1`, split policy `scenario-family-split-v1`
- corpus: `fixture-tldr-full-corpus-v1:d93ffff3c216b85caabdec2a36c6f20a9107526a32143a7bb2cc086dc77d5822`
- manifest SHA256: `68ae06300afdaee1515ef7c6248f35056e871e73d07778f2e1c2f636589c8461`
- dense recipe: `description`
- fusion: weighted reciprocal-rank fusion, keyword weight `1.0`, dense weight `1.0`
- displayed output: at most three distinct pages, one best example per page

Both retrievers use the same validated artifact, source/example IDs, platform
precedence (`target platform`, then `common`) and source-backed reference
policy. Page references never substitute a command or example. Candidate
budgets are page-level budgets: each side is reduced to its best ranked example
per selected page before fusion. The runner reports candidate recall separately
from display Success@1/3; ordering scores are not exposed as confidence.

## Candidate CLI

The development-only `askman_candidate` binary takes one explicit matching
bundle. Pass the same versioned bundle used by the evaluation benchmark; bundle
validation checks its manifest, component digests, pinned model assets, CLI
compatibility, and frozen dense recipe before querying. Querying does not fetch
assets or fall back to a single retriever.

```sh
cargo run --locked --offline --features dev --bin askman_candidate -- \
  --bundle /tmp/askman-matching-bundle \
  --linux search patterns files
```

This development binary uses the expanded-dev dense query mode. The shipping
`askman` binary uses the raw query even when built with the `dev` feature.
Use `--osx` or `--windows` for another target platform. `--verbose` exposes a
diagnostic normalized ranking score; it is not a confidence percentage. The
shipping `askman` binary now consumes the active validated bundle through the
same frozen hybrid path. `askman_candidate` remains available for
explicit-bundle comparison, while `tldr_subset query` and `dense-server`
remain available for keyword-only and dense-only diagnostics.

The provisioned offline harness builds the candidate and matching bundle, then
checks answerable, unanswerable, ambiguous, and cross-platform queries without
network access:

```sh
bash scripts/smoke_offline.sh candidate "$RUN_DIR"
```

## Development tuning

The bounded candidate set was run on the 30 development tasks before the
holdout run:

| Candidate | RRF k | page budget | weak cutoff |
| --- | ---: | ---: | ---: |
| `rrf-k20-b8-cutoff-0.00` | 20 | 8 | 0.00 |
| `rrf-k60-b8-cutoff-0.00` | 60 | 8 | 0.00 |
| `rrf-k60-b8-cutoff-0.50` | 60 | 8 | 0.50 |
| `rrf-k60-b12-cutoff-0.50` | 60 | 12 | 0.50 |
| `rrf-k20-b12-cutoff-0.50` | 20 | 12 | 0.50 |

Run each candidate with the existing evaluator, changing only
`--hybrid-candidate`:

```sh
python3 scripts/evaluate_retrieval.py \
  --artifact /tmp/askman-dense-description.db \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-dev-v1.json \
  --split dev --retriever hybrid \
  --hybrid-config tests/fixtures/evaluation/hybrid-config-v1.json \
  --hybrid-candidate rrf-k60-b8-cutoff-0.50 \
  --dense-helper /tmp/askman-run/target/debug/tldr_subset \
  --model-cache /tmp/askman-run/data/models \
  --output /tmp/hybrid-dev.json
```

The pinned model/runtime harness from
`docs/reproducibility/dense-retrieval.md` was used. The development comparison
was:

| Retriever/candidate | Candidate recall | Success@1 | Success@3 | Coverage | Incorrect answered | False unanswerable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| keyword | 13/13 | 13/13 | 13/13 | 13/30 | 0/13 | 0/17 |
| current-adapter | 13/13 | 13/13 | 13/13 | 13/30 | 0/13 | 0/17 |
| dense `description` | 13/13 | 12/13 | 13/13 | 30/30 | 0/13 | 17/17 |
| dense `description-plus-parent` | 13/13 | 12/13 | 13/13 | 30/30 | 0/13 | 17/17 |
| `rrf-k20-b8-cutoff-0.00` | 13/13 | 13/13 | 13/13 | 30/30 | 0/13 | 17/17 |
| `rrf-k60-b8-cutoff-0.00` | 13/13 | 13/13 | 13/13 | 30/30 | 0/13 | 17/17 |
| `rrf-k60-b8-cutoff-0.50` | 13/13 | 13/13 | 13/13 | 13/30 | 0/13 | 0/17 |
| `rrf-k60-b12-cutoff-0.50` | 13/13 | 13/13 | 13/13 | 13/30 | 0/13 | 0/17 |
| `rrf-k20-b12-cutoff-0.50` | 13/13 | 13/13 | 13/13 | 13/30 | 0/13 | 0/17 |

The frozen selection rule maximizes Success@3, then candidate recall, then
coverage, then lower total candidate budget, then lower RRF k, subject to no
increase in false answers and retaining both individual baselines. It selects
`rrf-k60-b8-cutoff-0.50`: the `0.50` cutoff restores selective coverage and
removes false answers, while the lower page budget wins the remaining tie.
The hybrid has no Success@1/3 lift over keyword on this fixture, so the result
is inconclusive and keyword remains a comparison baseline, not an automatic
fallback.

The same development metrics are stored under `development_results` in the
frozen config. Loading the config verifies every candidate and baseline,
development-only task count/denominators, the false-answer guardrail, and the
selected candidate produced by the rule. Holdout evaluation additionally
requires the recorded frozen config SHA256 above.

## Expanded development guard

PR #46's expanded-development guard is scored by the separately versioned
configuration
`tests/fixtures/evaluation/hybrid-config-expanded-dev-v1.json` and runner
`scripts/evaluate_retrieval_expanded_dev.py`. The frozen v1 evaluator and
`hybrid-config-v1.json` are not changed.

The selected development-only policy is:

- RRF `k=60`, keyword weight `1.0`, dense weight `1.05`, eight page candidates
  per side;
- retain dense candidates only when cosine distance is at most `0.55`;
- retain the fail-closed one-sided-match rule (`weak cutoff=0.50`);
- display at most three distinct pages.

Reproduce against the expanded development split only after provisioning the
pinned model/runtime and building the expanded bundle:

```sh
python3 scripts/evaluate_retrieval_expanded_dev.py \
  --artifact /tmp/askman-expanded-bundle/matching.db \
  --manifest tests/fixtures/tldr-evaluation-v2/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-dev-v2-expanded.json \
  --config tests/fixtures/evaluation/hybrid-config-expanded-dev-v1.json \
  --dense-helper /tmp/askman-run/target/debug/tldr_subset \
  --model-cache /tmp/askman-run/data/models \
  --output /tmp/evaluation-v2-expanded-dev-hybrid-v1.json
```

The scored local run used the pinned source digest and dataset/config/evaluator
digests recorded by the runner. Results:

| Retriever | Candidate recall | Success@1 | Success@3 | Coverage | Incorrect answered | False unanswerable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| keyword baseline | 1/30 | 1/30 | 1/30 | 1/60 | 0/1 | 0/30 |
| dense `description` | 26/30 | 18/30 | 26/30 | 60/60 | 4/30 | 30/30 |
| expanded hybrid v1 | 26/30 | 19/30 | 26/30 | 30/60 | 4/30 | 0/30 |

The machine-readable summary is
`docs/reproducibility/artifacts/evaluation-v2-expanded-dev-hybrid-v1.json`.

The dense-side bias is the smallest tested margin that lets the second-ranked
guarded dense result clear the strict `0.50` cutoff; equal weights leave a
dense-only result exactly at the cutoff and fail closed. The expanded hybrid
run is development evidence only: it does not authorize holdout access, a
main-versus-candidate A/B, or a release recommendation. Parent-description
dense indexing was also tested and scored below the frozen `description`
recipe (19/30 Success@3), so it was not selected.

### Expanded-dev query-expansion candidate

The next development candidate keeps the frozen evaluator, config, scorer,
bundle, distance guard, RRF policy, and page-level candidate budgets unchanged.
It only expands dense query text for three narrow intent families: file
contents sent to standard output, systemd restarts, and Linux IPv4 interface
observation. Added terms come from the pinned indexed example descriptions;
`address` is not added because it also occurs in add/delete descriptions and
would broaden the observation intent.

Query expansion is behind a development boundary. `askman_candidate` opts in
directly. Shipping `askman` and `dense-server` use raw queries by default. The
dense server accepts only the exact environment value below; any other value
fails closed. Set it only for this expanded-development evaluator invocation:

```sh
ASKMAN_DENSE_QUERY_MODE=expanded-dev \
DYLD_LIBRARY_PATH=/private/tmp/askman-issue31.Bco3g3/onnxruntime/onnxruntime-osx-arm64-1.20.0/lib \
LIBONNXRUNTIME_NO_PKG_CONFIG=1 \
ORT_LIB_LOCATION=/private/tmp/askman-issue31.Bco3g3/onnxruntime/onnxruntime-osx-arm64-1.20.0 \
ORT_PREFER_DYNAMIC_LINK=1 \
python3 scripts/evaluate_retrieval_expanded_dev.py \
  --artifact /private/tmp/askman-release-gate.pwfOOH/matching-bundle-expanded/matching.db \
  --manifest tests/fixtures/tldr-evaluation-v2/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-dev-v2-expanded.json \
  --config tests/fixtures/evaluation/hybrid-config-expanded-dev-v1.json \
  --dense-helper target/debug/tldr_subset \
  --model-cache /private/tmp/askman-release-gate.pwfOOH/matching-bundle-expanded/model-cache \
  --split dev \
  --output /tmp/evaluation-v2-expanded-dev-hybrid-query-expansion-v1.json
```

Do not set the opt-in for holdout or release-gate runs.

The versioned rerun is recorded in
`docs/reproducibility/artifacts/evaluation-v2-expanded-dev-hybrid-query-expansion-v1.json`:

| Candidate | Candidate recall | Success@1 | Success@3 | Coverage | Incorrect answered | False unanswerable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| expanded hybrid v1 | 26/30 | 19/30 | 26/30 | 30/60 | 4/30 | 0/30 |
| query expansion v1 | 30/30 | 23/30 | 30/30 | 30/60 | 0/30 | 0/30 |

All four remaining answerable misses return an acceptable example. This is
still development evidence only; holdout, release A/B, and remote CI remain
out of scope.

## Held-out check

Only after the config and selection rule were frozen, the selected candidate
was run with explicit holdout access. Keyword and hybrid agree on this small
fixture:

| Retriever | Candidate recall | Success@1 | Success@3 | Coverage | Incorrect answered | False unanswerable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| keyword | 10/10 | 10/10 | 10/10 | 10/30 | 0/10 | 0/20 |
| frozen hybrid | 10/10 | 10/10 | 10/10 | 10/30 | 0/10 | 0/20 |

The standalone dense candidate remains development-only under issue #18; the
hybrid holdout run is the later comparison path and uses the frozen dense
artifact without tuning. No new product scope is inferred from this result.

## Development quality blocker

The known [issue #18](https://github.com/0bmario/askman/issues/18) fixture
limitation contains only five operational examples and repeated paraphrase
families. It is suitable for reproducibility and guardrail checks, but not for
claiming production retrieval quality. Larger source-backed development
coverage is required before changing the product asset or fallback decision.
