# Source-backed operational fit v1 — development comparison

Status: **rejected for promotion**. Development evidence only; no holdout access.

Frozen cohort: 60 tasks, 28 supported and 32 unsupported; 12 families; 15 tasks/platform.
All 142 visible examples match between the scratch main database and candidate bundle. Main model assets match the pinned bundle. The blind source audit supplied labels before retrieval; it is not independent candidate validation.

| Run | Success@1 | Success@3 | Coverage | Incorrect answered | False answers |
| --- | ---: | ---: | ---: | ---: | ---: |
| Main reference | 19/28 | 21/28 | 50/60 | 5/26 | 24/32 |
| Control candidate | 23/28 | 25/28 | 49/60 | 1/26 | 23/32 |
| Treatment candidate | 16/28 | 17/28 | 21/60 | 1/18 | 3/32 |

Treatment vs control: **S@1 -7/28; S@3 -8/28; coverage -28/60; false answers -20/32.** The hard filter suppresses many false answers but removes too many supported results.

| Platform | Control S@1 | Treatment S@1 | Control S@3 | Treatment S@3 | False answers control → treatment | Coverage control → treatment |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 6/7 | 5/7 | 7/7 | 5/7 | 5/8 → 1/8 | 12/15 → 6/15 |
| linux | 6/7 | 4/7 | 7/7 | 5/7 | 7/8 → 2/8 | 14/15 → 7/15 |
| osx | 5/8 | 4/8 | 5/8 | 4/8 | 5/7 → 0/7 | 11/15 → 4/15 |
| windows | 6/6 | 3/6 | 6/6 | 3/6 | 6/9 → 0/9 | 12/15 → 4/15 |

Offline: both runs had zero CLI execution failures under `macOS sandbox-exec deny network*`. Resource checks stayed within 20%: treatment vs control warmed p95 86.611 ms (-0.45%), warmed peak memory 237290192 B (+0.43%). Quality, not performance, rejects this candidate.

The control candidate measured 23/28 S@1 and 25/28 S@3 vs main 19/28 and 21/28. Treatment fell to 16/28 and 17/28; its gate reports overall S@1 below main and S@3 regressions on common, Linux, and Windows. Treatment reduced unsupported-query false answers 23/32 → 3/32, while coverage fell 49/60 → 21/60.

The filter is off by default and remains experimental. Keep shipped main. Do not tune it on this cohort. A follow-up would need a fresh development cohort and a different, softer compatibility approach. Independent validation still requires a new unseen holdout and fresh explicit authorization. The installed v0.3.3 behavior sample is separate because its database has 30,205 vector rows, not this pinned 142-example corpus.

Artifacts:

- [Control canonical dev gate](operational-example-fit-v1-control.md)
- [Treatment canonical dev gate](operational-example-fit-v1-treatment.md)
- [Freeze manifest](operational-compatibility-dev-v2-freeze.json)
- [Frozen dataset](../../../tests/fixtures/evaluation/operational-compatibility-dev-v2.json)
- [Experiment protocol](operational-example-fit-v1-protocol.md)
