# Better Askman release gate

`retrieval-v2` is promoted as the Better Askman only when every condition below
holds in a paired comparison against `main` on `evaluation-v2`. Evaluate
task-level, user-visible outcomes: displayed examples and abstentions.

Run both CLIs with identical task inputs, target-platform flags, pinned
corpus/bundle and model/asset digests, runtime configuration, and network
policy. Capture both commits, lockfiles, and runtime metadata.

- `Success@1` is acceptable first displayed examples divided by answerable
  tasks. `Success@3` is answerable tasks with at least one acceptable result
  in the first three displayed results divided by answerable tasks. The
  incorrect-answer rate is incorrect answered tasks—answerable tasks with a
  non-empty displayed result and no acceptable displayed ID in the first three
  results—divided by answered answerable tasks—answerable tasks with a
  non-empty displayed result. The false-answer rate is unanswerable tasks with
  a non-empty result divided by unanswerable tasks.
- The overall paired `Success@1` gain (`retrieval-v2` minus `main`) is at least five percentage points.
- Paired `Success@1` gains are positive in at least two scenario families, with no negative paired `Success@1` gain in any scenario family. Each family uses its answerable tasks as the denominator.
- There is no regression in `Success@3`, incorrect-answer rate, or false-answer
  rate overall or for any target platform (`common`, `linux`, `osx`,
  `windows`). Both implementations pass the same network-disabled offline
  checks; network policy, setup/query separation, and exit statuses must not
  regress. Expected CLI results may differ when retrieval changes them and are
  scored as user-visible outcomes.
- A fixed-seed, 10,000-resample paired bootstrap for the overall paired `Success@1` gain has a 95% interval wholly above zero.
- Warmed-query p95 latency and peak memory are each no more than 20% above `main`.

The evidence report includes exact counts and denominators, overall and
platform/family breakdowns, failure examples, reproduction commands,
limitations, and a Better Askman or inconclusive recommendation.

Otherwise the result is inconclusive.
