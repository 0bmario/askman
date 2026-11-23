# Dense candidate budget v1 — development comparison

**Scope:** development-only evidence; not independent validation or a release decision. Holdout was not accessed.

| System | Success@1 | Success@3 | Coverage | False answers | Incorrect supported answers |
|---|---:|---:|---:|---:|---:|
| Source-built main | 16/26 | 17/26 | 46/60 | 24/34 | 5/22 |
| Control (8) | 20/26 | 21/26 | 44/60 | 22/34 | 1/22 |
| Treatment (16) | 20/26 | 21/26 | 44/60 | 22/34 | 1/22 |

## Decision

**reject-budget-16**. At least one preregistered development criterion failed; do not tune on this cohort.

Budget 8 vs 16 was the only configuration difference. Both arms used the same candidate commit, source hash and binary hash; the canonical network-denied development runs completed with no CLI failures.

| Platform | Main S@1/S@3, coverage | Budget 8 S@1/S@3, coverage | Budget 16 S@1/S@3, coverage |
|---|---:|---:|---:|
| common | 6/8, 7/8, 10/15 | 6/8, 7/8, 10/15 | 6/8, 7/8, 10/15 |
| Linux | 4/7, 4/7, 10/15 | 5/7, 5/7, 10/15 | 5/7, 5/7, 10/15 |
| macOS | 5/6, 5/6, 14/15 | 6/6, 6/6, 14/15 | 6/6, 6/6, 14/15 |
| Windows | 1/5, 1/5, 12/15 | 3/5, 3/5, 10/15 | 3/5, 3/5, 10/15 |

Thus both candidate arms lose two covered Windows tasks versus source-built main. Fresh-process p95/memory were 95.994 ms/282,837,736 B for budget 8 and 90.298 ms/254,034,616 B for budget 16. Warm p95/memory were 88.958 ms/237,732,536 B and 88.146 ms/237,470,416 B. All are within the preregistered 20% guardrail. Both canonical gate reports say `inconclusive` because they were dev-only runs.

The frozen aggregate source hash omitted `.cargo/config.toml`; both gate reports captured the same complete working-tree and binary hashes. One post-run aggregate-inspection command also printed a truncated sample of task-level dev failures; no tuning followed. See the append-only [freeze correction](dense-budget-dev-v1-freeze-correction.md).

The installed-product smoke remains separate and was not scored with these labels. A dev result cannot authorize holdout access.
