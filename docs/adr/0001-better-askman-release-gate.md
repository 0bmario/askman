# Better Askman release gate

`retrieval-v2` is promoted as the Better Askman only when it achieves all of the following against `main` on the paired release benchmark:

- At least a five-percentage-point absolute gain in paired `Success@1` across at least two scenario families.
- No regression in any scenario family.
- No regression in `Success@3`, incorrect answers, false answers, platform behavior, or offline behavior.
- A fixed-seed, 10,000-resample paired bootstrap has a positive 95% interval for the `Success@1` gain.
- Warmed-query p95 latency and peak memory regress by no more than 20%.

Otherwise the result is inconclusive. The comparison must use user-visible CLI results and pinned inputs; the release benchmark policy is defined in ADR 0002.
