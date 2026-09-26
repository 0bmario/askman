# ADR 0003 — Hybrid rank fusion

Status: Superseded on 2026-09-26. Hybrid RRF is not used by the experimental
dense-only candidate path. The earlier candidate failed independent
validation; the current smaller candidate has dev-only evidence and is not
approved for release pending authorized independent evaluation.

## Original decision

The initial v2 plan combined lexical and dense rankings with reciprocal-rank
fusion, displayed at most three destination pages, and abstained when no
candidate passed explicit guards. That design also added action and negation
filters to avoid examples that contradicted the request.

## Superseding decision (historical broad candidate)

The first development candidate used dense-only retrieval with main's
stored-text recipe. Apply the frozen
`IntentRulesV1` query expansions, rank by raw cosine distance, retain candidates
at distance `<= 0.55`, and display at most three distinct pages. If none qualify,
print `No good matches found.` The distance cutoff is a development-derived
retrieval threshold, not a confidence score.

Do not fuse lexical and dense results in the product path. Keep the lexical
index for reproducible ablations and label/index checks. Keep early per-page
selection: late example diversity raised candidate recall in the measured
ablation but reduced Success@3.

The frozen v2 development run on identical parser-v3/v4 records measured:

| Candidate | Success@1 | Success@3 | False answers |
| --- | ---: | ---: | ---: |
| Main CLI | 18/30 | 23/30 | 1/30 |
| Dense, main-compatible text, raw query, `<= 0.55` | 20/30 | 24/30 | 0/30 |
| Dense plus `IntentRulesV1`, `<= 0.55` | 30/30 | 30/30 | 0/30 |
| Hybrid plus the same expansions and guards | 30/30 | 30/30 | 0/30 |

Hybrid adds no measured value to the selected dense candidate. The canonical
dev-only gate also measured main 18/30 versus candidate 30/30 Success@1, main 23/30
versus candidate 30/30 Success@3, and one versus zero false answers. These are
development results; `IntentRulesV1` was tuned on these same development tasks.
Do not tune it on holdout results. The candidate needs the explicitly
authorized independent gate before a release decision.

The full ablation and paired dev-only gate reports are in
[`retrieval-v2-controlled-ablation-dev-v1.json`](../reproducibility/artifacts/retrieval-v2-controlled-ablation-dev-v1.json)
and
[`main-vs-retrieval-v2-dev-only-v2.json`](../reproducibility/artifacts/main-vs-retrieval-v2-dev-only-v2.json).
The earlier paired run remains preserved in
[`main-vs-retrieval-v2-dev-only-v1.json`](../reproducibility/artifacts/main-vs-retrieval-v2-dev-only-v1.json)
to show resource-measurement variance.

## Promotion decision after authorized evaluation

The latest candidate was frozen at source digest
`419c2a86c559735bd62173885371bd78e67e4c4c8414eef01f05917813bf046d` before the
canonical run. On development it reached 30/30 `Success@1` and `Success@3`.
On the 30-answerable-task holdout, it tied main at 19/30 `Success@1`, fell from
25/30 to 20/30 `Success@3`, and tied false answers at 6/30. Holdout platform
`Success@3` fell on macOS (10/10 to 8/10) and Windows (4/5 to 1/5). This fails
the independent improvement and no-regression conditions, even though the
runner's pooled gate recommendation is `better_askman`.

Keep dense-only as a development candidate only. Do not promote it or adjust
it from holdout outcomes. The evaluated holdout is consumed; another candidate
needs a new unseen split. Hybrid remains unjustified by development ablations:
it tied dense-only and added no measured value.

## Current development candidate (2026-09-26)

Select dense-only retrieval with the main-compatible embedding text, five
focused intent rules with six source-backed `FocusedIntentRulesV1` query
expansions, raw cosine-distance
ranking, a `<= 0.55` cutoff, and early one-example-per-page selection. This
replaces the broader `IntentRulesV1` development candidate; the broad mode
remains available for historical ablations. Do not add lexical/dense fusion:
it again tied the expanded dense result and added no measured value.

On the identical 60-task dev split and pinned 142 records, the focused
candidate measured 30/30 Success@1, 30/30 Success@3, and 0/30 false answers.
Main measured 18/30, 23/30, and 1/30. The latest paired canonical dev-only
gate had zero execution failures, common/Linux/macOS/Windows Success@1 of
10/10, 10/10, 5/5, and 5/5, and no platform regressions. Network-denied
execution passed. Warm p95 was 85.001 ms for the candidate vs 86.343 ms for
main; peak memory was 236,536,504 B vs 236,077,752 B. Fresh-process p95 was
85.653 ms vs 89.266 ms; peak memory was 282,936,040 B vs 236,438,200 B (19.7%
higher). Every measured phase stayed within the 20% ceiling. This is
development evidence only; earlier focused runs remain recorded to show
measurement variance.

The committed candidate is `3494a11`; source digest
`ac58a8c3c63390b31f0af599be4939be49e87510e28282be6d8a6c276164dfa2`; binary
digest `2e03c4d99601b9d14f1dc0ad63545c12b274ddc5356abbaa043d8b914ce80521`.
It abstains on negated file-to-stdout requests and when a request excludes
`cat`, the pinned corpus's only verified full-file stdout example. The new
direct dev CLI check had exposed `cat` at distance `0.4489` for “do not show
file contents to stdout”; the final build abstains. The independent holdout is
frozen but unscored. Require explicit authorization before the canonical
paired run; do not tune from its result.

The controlled results are in
[`retrieval-v2-controlled-ablation-dev-v2.json`](../reproducibility/artifacts/retrieval-v2-controlled-ablation-dev-v2.json)
and the latest paired development run is in
[`main-vs-retrieval-v2-focused-dev-only-v5.json`](../reproducibility/artifacts/main-vs-retrieval-v2-focused-dev-only-v5.json).
The previous focused runs remain in
[`main-vs-retrieval-v2-focused-dev-only-v4.json`](../reproducibility/artifacts/main-vs-retrieval-v2-focused-dev-only-v4.json),
[`main-vs-retrieval-v2-focused-dev-only-v3.json`](../reproducibility/artifacts/main-vs-retrieval-v2-focused-dev-only-v3.json),
[`main-vs-retrieval-v2-focused-dev-only-v2.json`](../reproducibility/artifacts/main-vs-retrieval-v2-focused-dev-only-v2.json) and
[`main-vs-retrieval-v2-focused-dev-only-v1.json`](../reproducibility/artifacts/main-vs-retrieval-v2-focused-dev-only-v1.json).

## Constraints

- Preserve offline query operation, pinned model assets, and immutable bundle
  activation/rollback.
- For explicit network allow/block, tar extraction, DNS cache invalidation,
  recursive text search, negated EXIF observation, and negated or explicitly
  unsupported file-to-stdout requests, return only a grounded example;
  otherwise abstain.
- Keep command/example rendering and platform selection covered by the paired
  gate.
- A learned reranker or model replacement remains out of scope until dense-only
  retrieval fails an authorized independent evaluation.
