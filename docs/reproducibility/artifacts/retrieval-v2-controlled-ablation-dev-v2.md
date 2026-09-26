# Controlled retrieval ablation — development only

Run on the frozen 60-task dev split and identical parser-v3/v4 corpus records
(142 visible examples). No holdout tasks were queried or scored. Full inputs,
task-level results, resource data, and source hashes are in
[`retrieval-v2-controlled-ablation-dev-v2.json`](retrieval-v2-controlled-ablation-dev-v2.json).

## Results

Counts below use 30 answerable tasks for Success@1/3 and 30 unanswerable tasks
for false answers.

| Variant | Success@1 | Success@3 | False answers |
| --- | ---: | ---: | ---: |
| Main CLI | 18/30 | 23/30 | 1/30 |
| Main-compatible dense, raw query, cutoff 0.55 | 20/30 | 24/30 | 0/30 |
| Main-compatible dense, focused-v1 rules, cutoff 0.55 | 30/30 | 30/30 | 0/30 |
| Main-compatible dense, full IntentRulesV1, cutoff 0.55 | 30/30 | 30/30 | 0/30 |
| Hybrid with full IntentRulesV1 | 30/30 | 30/30 | 0/30 |
| Description-only dense, cutoff 0.55 | 22/30 | 26/30 | 0/30 |
| Description plus parent, cutoff 0.55 | 13/30 | 18/30 | 0/30 |

`focused-v1` keeps five narrowly scoped, source-backed vocabulary mappings. It
matches the larger rule set on dev with less query logic. These are development
results, not independent validation.

## Isolated factors

- **Abstention:** main-compatible raw dense at cutoff 0.55 answers 30/30
  answerable tasks, abstains on all 30 negatives, and scores 20/24. At cutoff
  0.60 it keeps the same relevance and adds one false answer; without a cutoff
  it answers all negatives. Keep 0.55.
- **Example selection:** expanding retrieval to same-page examples raises
  candidate recall 24/30→30/30 but leaves Success@1/3 at 20/24. Delaying page
  diversity in hybrid lowers Success@3 24/30→20/30. Keep one example per page
  before display.
- **Ranking:** legacy command preferences, partial preference blends, and
  platform biases do not improve raw dense results. A small lexical reranker
  reaches 21/25, still below focused rules.
- **Fusion:** guarded hybrid ties dense on raw and expanded queries. It adds no
  measured value, so the product path stays dense-only.
- **Representation:** description-only beats main-compatible raw on this dev
  slice (22/26 vs 20/24); parent text falls to 13/18. Main-compatible text
  remains the selected representation because it reproduces installed main's
  embedding input exactly; focused query rules supply the measured dev lift.

All runs use the same pinned parser records. This file records development
evidence only; the fresh holdout remains frozen and unscored pending explicit
authorization.
