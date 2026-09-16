# Better Askman release gate

`retrieval-v2` is promoted as the Better Askman only when every condition below holds in a paired comparison against `main` on `evaluation-v2`. Evaluate task-level, user-visible outcomes: displayed examples and abstentions.

- `Success@1` is acceptable first displayed examples divided by answerable tasks. `Success@3` is answerable tasks with at least one acceptable result in the first three displayed results divided by answerable tasks. The incorrect-answer rate is answerable tasks with an incorrect displayed result divided by answerable tasks. The false-answer rate is unanswerable tasks with a non-empty result divided by unanswerable tasks.
- The overall paired `Success@1` gain (`retrieval-v2` minus `main`) is at least five percentage points.
- Paired `Success@1` gains are positive in at least two scenario families, with no negative paired `Success@1` gain in any scenario family. Each family uses its answerable tasks as the denominator.
- There is no regression in `Success@3`, incorrect-answer rate, or false-answer rate overall or for any target platform (`common`, `linux`, `osx`, `windows`). Both implementations also pass the same network-disabled offline checks with no changed expected output or exit status.
- A fixed-seed, 10,000-resample paired bootstrap for the overall paired `Success@1` gain has a 95% interval wholly above zero.
- Warmed-query p95 latency and peak memory are each no more than 20% above `main`.

Otherwise the result is inconclusive.
