# ADR 0003 — Hybrid rank fusion

Status: Superseded as a product decision. Reciprocal-rank fusion remains out:
it tied dense-only in controlled development ablations. Later candidates,
including the focused query-rule candidate, description-only recipe, and
source-backed example-fit filter, did not satisfy release guardrails. Keep
shipped main. A changed candidate needs a fresh authorized holdout before
promotion.

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

At this stage, the product candidate did not load or fuse lexical candidates.
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

## Earlier focused candidate selected on the original dev split (2026-09-26)

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
file contents to stdout”; the final build abstains. The independent holdout
result is recorded below; do not tune from it.

## Independent fresh holdout result (2026-09-26)

The candidate was scored once, without post-freeze changes, against fresh
holdout v1. Main/candidate results were `Success@1` 13/30→15/30,
`Success@3` 19/30→15/30, incorrect answered tasks 7/26→10/25, and false
answers 13/30→8/30. The observed `Success@1` gain was 6.7 points, but its
one-sided 95% paired-bootstrap lower bound was −3.3 points. Linux and Windows
also regressed on `Success@3`; no CLI failures occurred under the network-denied
wrapper, and holdout fresh/warmed latency and memory stayed within the 20%
limits. The independent gate is inconclusive and the candidate is not approved.

Do not adjust retrieval from this result. Fresh holdout v1 is consumed; any
changed candidate needs another unseen split and explicit scoring
authorization. Hybrid remains unjustified by the development ablations. Full
evidence:
[`main-vs-retrieval-v2-focused-fresh-holdout-v1.json`](../reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v1.json)
and its
[`rendered report`](../reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v1.md).

## New development cohort (2026-09-26)

The earlier dense candidate and RRF ablations were measured on development
tasks and did not establish independent improvement. A new 60-task dev-only
cohort was authored and frozen before retrieval runs, against the same pinned
142-record parser-v4 corpus. The controlled one-factor runs show:

| Variant | Success@1 | Success@3 | Incorrect answered | Decision signal |
| --- | ---: | ---: | ---: | --- |
| Main | 13/30 | 21/30 | 3/24 | Reference |
| Focused dense, one/page, cutoff 0.55 | 14/30 | 14/30 | 8/22 | Top-three and answer safety regress |
| Same-page selection, cutoff 0.55 | 14/30 | 19/30 | 3/22 | Restores some top-three usefulness |
| Same-page, cutoff 0.60 | 14/30 | 21/30 | 3/24 | Ties main on top-three and safety |
| Broader intent rules, same-page, cutoff 0.60 | 14/30 | 21/30 | 3/24 | Ties focused query rules |
| Focused + same-page + cutoff 0.60 + lexical 0.05 | 15/30 | 22/30 | 2/24 | Best measured dev variant |

The selected variant keeps the main-compatible embedding text and focused
query rules. It retrieves a dense top-eight pool, keeps same-page examples,
rejects candidates above raw cosine distance 0.60, then reranks eligible
examples by subtracting 0.05 per shared non-stopword token. The raw distance
still controls abstention. This simple reranker is distinct from RRF: RRF
showed no additional value, while lexical reranking gained two first-result
tasks and one top-three task on this dev cohort.

Against main, the selected candidate has 0 false answers (main 0/30), 24/60
coverage (main 24/60), and 2/24 incorrect answered tasks (main 3/24). Success@1
is common 3/10 vs 2/10, Linux 2/5 vs 1/5, macOS 8/10 vs 8/10, Windows 2/5 vs
2/5. Success@3 is common 7/10 vs 7/10, Linux 4/5 vs 3/5, macOS 9/10 vs 9/10,
Windows 2/5 vs 2/5. No family regressed; two families improved. The observed
Success@1 gain is 2/30 (6.7 pp), but the fixed-seed one-sided 95% paired
bootstrap lower bound is 0.0 pp. Network-denied CLI execution had no failures.
Fresh-process p95/memory were 84.511 ms / 256,328,376 B vs main 86.721 ms /
237,028,024 B. Warm p95/memory were 84.399 ms / 237,765,328 B vs main 85.258
ms / 235,930,296 B. All resource deltas are within 20%.

The canonical runner decision remains inconclusive: the development bootstrap
lower bound is not above zero, and dev-only evidence cannot make a release
decision. This candidate was selected using only the frozen development
cohort; it still requires a new unseen holdout and explicit scoring
authorization. The original holdout v1 is consumed and was not used for tuning.
Machine-readable and rendered variant reports are linked from
[`retrieval-v2-approach-review.md`](../retrieval-v2-approach-review.md).
A separate holdout v2 was frozen for this candidate and later scored once after
explicit authorization. Its independent result is recorded below. See
[`fresh-holdout-v2-freeze.md`](../reproducibility/fresh-holdout-v2-freeze.md).

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
- A learned reranker or model replacement may be considered in future
  development-only experiments; any release claim still needs a fresh
  independently authorized holdout run.

## Independent fresh holdout v2 result (2026-09-26)

Candidate ba74692cf79fa9c294f685fbade8f9315aeacdd1 was scored once after
explicit authorization. On the 30 answerable holdout tasks, main/candidate
measured Success@1 12/30 to 15/30 and Success@3 13/30 to 17/30. Incorrect
answered tasks fell 9/22 to 3/20; false answers tied at 5/30. The one-sided
95% paired-bootstrap lower bound was 0.0, and common-platform Success@3 fell
4/7 to 3/7. The canonical gate is inconclusive; keep shipped main. Offline
execution had no failures and all resource phases remained within 20%. Do not
tune from this consumed holdout. RRF remains out; the lexical reranker has
development and independent evidence of improvement, but it does not meet
the release guardrails. Full report:
[main-vs-retrieval-v2-focused-fresh-holdout-v2.json](../reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v2.json)
and
[rendered report](../reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v2.md).

## Amendment (2026-09-27): source-backed focused query rules

Controlled development experiments selected two deterministic rewrites atop
the existing focused rules: non-Windows searches that identify files and an
extension/pattern append `Find files by extension`; Windows move requests that
identify distinct drives append `Move a file or directory across drives`.
Both use corpus wording and remain guarded against negation. Product ranking,
same-page candidate selection, 0.60 raw-distance abstention, and 0.05 lexical
reranking stay fixed. The combined rule set improved the dev-extension cohort
and passed the development-only platform, false-answer, network, latency, and
memory checks. Fresh-process candidate memory was close to the 20% ceiling.

This is the selected development candidate, not the shipped path. The new
rules were selected on dev-extension tasks; neither earlier consumed holdout
was used for tuning. At this point v3 was frozen and awaited authorization;
its later result is recorded below. RRF remains out: it has not demonstrated
additional value over dense retrieval.
Exact CLI and isolated ablation reports are linked in
[`retrieval-v2-approach-review.md`](../retrieval-v2-approach-review.md).

## Independent fresh holdout v3 result (2026-09-27)

After explicit authorization, the focused query-rule candidate was scored
once against installed main on the frozen v3 holdout. Success@1 improved
12/30→18/30 and Success@3 16/30→22/30; false answers tied at 0/30. The
one-sided 95% paired-bootstrap lower bound was 6.7 pp. The independent decision
is **inconclusive** because common-platform Success@3 regressed 5/8→4/8,
incorrect answered tasks rose 1/6→1/5, and the markdown-extension family
regressed at Success@1. Offline execution had no failures, and measured
latency and memory stayed within limits. Keep shipped main; RRF remains out.

Holdout v3 is consumed. Do not tune from it or score it again. Further
development must not use its outcomes; any later candidate needs a new unseen
holdout and explicit authorization for independent evaluation. Report:
[`main-vs-retrieval-v2-focused-query-rules-fresh-holdout-v3.md`](../reproducibility/artifacts/main-vs-retrieval-v2-focused-query-rules-fresh-holdout-v3.md).

## Amendment (2026-09-27): description-only recipe rejected

A one-factor dev-only A/B changed only the dense embedding recipe on the same
60 audited tasks and 142 parser-v4 records. Control used main-compatible text;
treatment embedded only the example description. Treatment fell from 11/30 to
9/30 Success@1 relative to control, tied its 14/30 Success@3, and increased
false answers from 23/30 to 29/30 and incorrect answered rate from 1/15 to
9/23. It also regressed Linux and macOS results. Latency passed, but fresh
memory was 18.8% above installed main, near the 20% ceiling. Reject the recipe
without tuning. The comparison is development evidence only; the earlier
focused-candidate holdout does not validate this recipe. Keep shipped main; any
future independent evaluation needs a new unseen holdout and explicit
authorization. See the
[dev comparison](../reproducibility/artifacts/description-embedding-dev-v3-comparison.md)
and [protocol](../reproducibility/artifacts/description-embedding-dev-v3-protocol.md).

## Amendment (2026-09-27): hard operational-example fit filter rejected

A one-factor experiment held the dense recipe, focused-v2 query mode and
rewrites, candidate budget, platform selection, 0.60 cutoff, lexical reranking,
abstention guards, and top-three limit fixed. Treatment checked explicit query
actions and constraints against each example's description and command before
the existing ranking. Page overview text was excluded.

On the independently source-labeled development cohort, the main-compatible
control measured 23/28 Success@1, 25/28 Success@3, 49/60 coverage, and 23/32
false answers. The hard-filter treatment measured 16/28, 17/28, 21/60, and
3/32. Against control it lost seven first-result and eight top-three tasks,
while abstaining on 28 additional prompts. Success@1 fell on every platform;
Success@3 regressed on common, Linux, and Windows versus main. It is rejected.

Both runs completed offline with no CLI failures. Treatment latency and memory
stayed within the 20% resource guardrail. The canonical `--dev-only` report is
not independent validation and cannot authorize release. No holdout data was
accessed. Keep this filter off; do not tune it on this cohort. At that time,
a softer constraint-aware reranker was only a hypothesis; its later
fresh-cohort result is recorded below.

The author draft expected 30/30 answerability balance; the independent source
audit established 28 supported and 32 unsupported prompts. The audited labels
were adopted. The raw prompt metadata had confused source digest with literal
manifest-file SHA; the frozen dataset records the literal SHA without changing
prompt text or labels. The initial v1 freeze is preserved unscored after a
preflight validation error; v2 is the freeze used for these runs. Full
provenance and metrics:
[`operational-example-fit-v1-comparison.md`](../reproducibility/artifacts/operational-example-fit-v1-comparison.md),
[control](../reproducibility/artifacts/operational-example-fit-v1-control.md),
[treatment](../reproducibility/artifacts/operational-example-fit-v1-treatment.md),
[protocol](../reproducibility/artifacts/operational-example-fit-v1-protocol.md).

## Amendment (2026-09-27): bounded soft-fit reranking rejected

A fresh one-factor development experiment added `0.05 × unsupported_fraction`
to the existing lexical-adjusted distance. The source audit labeled 29/60
tasks answerable after a separate source-only adjudication rejected one task
that required composing two examples. On the same 142 parser-v4 records, the
unchanged control scored 19/29 Success@1, 22/29 Success@3, 41/60 coverage,
and 17/31 false answers; treatment scored 18/29, 22/29, 41/60, and 17/31.
Linux Success@1 fell 5/7→4/7. The soft penalty added no value and is rejected.

Control improved over the pinned-record main reference at Success@1 (13/29→
19/29) and Success@3 (15/29→22/29), but false answers rose 16/31→17/31.
Treatment could not address that safety regression because it only changes
rank order. Both network-denied dev-only gates completed without CLI failures;
resource use stayed within 20%. The canonical decision is inconclusive because
the cohort is development-only and one family also regressed at Success@1. No
holdout data was accessed. Keep shipped main; do not tune on this cohort. Full
evidence is in the
[soft-fit comparison](../reproducibility/artifacts/operational-soft-fit-dev-v1-comparison.md),
[canonical control](../reproducibility/artifacts/operational-soft-fit-dev-v1-control.md),
[treatment](../reproducibility/artifacts/operational-soft-fit-dev-v1-treatment.md),
and [frozen protocol](../reproducibility/artifacts/operational-soft-fit-dev-v1-protocol.md).

## Amendment (2026-09-27): wider dense candidate budget rejected

A fresh source-audited 60-task development cohort tested one change: dense
candidate budget 8→16. Embeddings, query rules, platform selection, lexical
reranking, cutoff, abstention guards, and top-three display stayed fixed.
Treatment tied control on every aggregate quality count: 20/26 Success@1,
21/26 Success@3, 44/60 coverage, 22/34 false answers, and 1/22 incorrect
supported answers. The source-built main reference measured 16/26, 17/26,
46/60, 24/34, and 5/22 respectively. The working-tree control's gain over main
is not attributable to candidate budget; only treatment-minus-control
isolates that factor.

The 16-candidate setting adds no quality value and is rejected. Both arms had
zero network-denied CLI failures and stayed within the resource limit. Their
canonical reports are `inconclusive` because they are dev-only. The cohort is
fully inspected development data and must not be used to tune another
candidate. No holdout data was accessed; the actual installed-product sample
remains separate. See the
[comparison](../reproducibility/artifacts/dense-budget-dev-v1-comparison.md),
[frozen protocol](../reproducibility/artifacts/dense-budget-dev-v1-protocol.md),
[freeze](../reproducibility/artifacts/dense-budget-dev-v1-freeze.json), and
[freeze correction](../reproducibility/artifacts/dense-budget-dev-v1-freeze-correction.md).
