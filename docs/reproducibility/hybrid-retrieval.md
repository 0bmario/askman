# Hybrid retrieval comparison

Issue #19 adds a development-only hybrid candidate to the frozen retrieval
evaluation. It fuses the existing keyword and dense candidate IDs; it does not
change the shipping CLI, install flow, model assets, or database distribution.

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
