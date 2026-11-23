# Operational soft-fit v1 — development comparison

Status: **rejected for promotion**. Development evidence only; no holdout access. The independent source audit labels prompts against the pinned corpus; it is not independent candidate validation.

Frozen cohort: 60 tasks, 29 supported and 31 unsupported; 12 families; 15 tasks/platform. Dataset SHA-256 `418ac923013146d3b60d920aba50a5d9f69afd3da1c658495c226b648a772daa`; freeze manifest SHA-256 `093aefd39bc81f91fb66a99322d0e761d7eabbb51589639ebcfd57bab0607ac1`.

The pinned corpus contains 24 pages and 142 operational examples. Main and candidate used the same visible example inventory and matching model assets; the scratch main DB itself does not have the pinned baseline DB hash. See the machine report for exact digests.

| Run | Success@1 | Success@3 | Coverage | Incorrect answered | False answers |
| --- | ---: | ---: | ---: | ---: | ---: |
| Main source-build reference on pinned records | 13/29 | 15/29 | 39/60 | 8/23 | 16/31 |
| Fixed-retrieval control | 19/29 | 22/29 | 41/60 | 2/24 | 17/31 |
| Soft-fit treatment | 18/29 | 22/29 | 41/60 | 2/24 | 17/31 |

Treatment vs control: **Success@1 −1/29; Success@3 0; coverage 0; incorrect answered 0; false answers 0.** Treatment lost one first result while leaving top-three, coverage, and false-answer rates unchanged. Against main, treatment gained five S@1 and seven S@3 tasks but had one additional false answer.

| Platform | Main S@1 / S@3 | Control S@1 / S@3 | Treatment S@1 / S@3 | False answers main → treatment | Coverage main → treatment |
| --- | ---: | ---: | ---: | ---: | ---: |
| common | 2/7 / 2/7 | 3/7 / 3/7 | 3/7 / 3/7 | 5 → 5 | 9/15 → 9/15 |
| linux | 5/7 / 6/7 | 5/7 / 6/7 | 4/7 / 6/7 | 4 → 3 | 10/15 → 9/15 |
| osx | 4/8 / 5/8 | 7/8 / 8/8 | 7/8 / 8/8 | 3 → 5 | 11/15 → 13/15 |
| windows | 2/7 / 2/7 | 4/7 / 5/7 | 4/7 / 5/7 | 4 → 4 | 9/15 → 10/15 |

The treatment regressed Linux Success@1 from 5/7 to 4/7 versus control; other platform S@1 tied. It did not demonstrate additional value over control. The control itself raised false answers from main’s 16/31 to 17/31, which the rank-only treatment could not fix.

| Candidate arm | Fresh p95 (candidate / main) | Fresh peak memory (candidate / main) | Warm p95 (candidate / main) | Warm peak memory (candidate / main) |
| --- | ---: | ---: | ---: | ---: |
| Control | 94.503 / 97.956 ms | 269,402,808 / 237,814,504 B | 104.848 / 97.901 ms | 237,896,376 / 237,421,264 B |
| Treatment | 98.661 / 97.816 ms | 268,714,680 / 237,847,248 B | 97.231 / 97.038 ms | 237,159,096 / 236,143,288 B |

Both canonical `--dev-only` runs completed under `macOS sandbox-exec deny network*` with no query failures. All reported resource comparisons stayed within the 20% guardrail; treatment fresh-process peak memory was 13.0% above its same-run main reference.

The canonical runner returned **inconclusive** for both arms. This is expected for custom dev-only evidence and is not independent validation. No holdout dataset, labels, or query outputs were read.

The actual installed v0.3.3 behavior sample remains separate: its database has 30,205 rows and a different corpus, so these 142-example labels cannot score it. See [`installed-v0.3.3-smoke-v1.json`](installed-v0.3.3-smoke-v1.json).

The blind auditor initially counted numeric sort plus in-place output as a composed answer. A separate source-only adjudication applied the individual-example rule: no single corpus example provides both, so the frozen label is unsupported. Raw labels, audit, and adjudication are all preserved.

Artifacts: [protocol](operational-soft-fit-dev-v1-protocol.md), [control](operational-soft-fit-dev-v1-control.md), [treatment](operational-soft-fit-dev-v1-treatment.md), [freeze](operational-soft-fit-dev-v1-freeze.json), [dataset](../../../tests/fixtures/evaluation/operational-soft-fit-dev-v1.json), and [machine comparison](operational-soft-fit-dev-v1-comparison.json).
