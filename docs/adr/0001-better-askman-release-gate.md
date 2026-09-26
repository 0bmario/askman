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
- The overall paired `Success@1` gain (`retrieval-v2` minus `main`) is at least
  five percentage points.
- Paired `Success@1` gains are positive in at least two scenario families, with
  no negative paired `Success@1` gain in any scenario family. Each family uses
  its answerable tasks as the denominator.
- There is no regression in `Success@3`, incorrect-answer rate, or false-answer
  rate overall or for any target platform (`common`, `linux`, `osx`,
  `windows`). Both implementations pass the same network-disabled offline
  checks; network policy, setup/query separation, and exit statuses must not
  regress. Expected CLI results may differ when retrieval changes them and are
  scored as user-visible outcomes.
- A fixed-seed, 10,000-resample paired bootstrap for the overall paired
  `Success@1` gain has a 95% interval wholly above zero.
- Fresh-process p95 latency and peak memory for every evaluated split, plus
  warmed-query p95 latency and peak memory, are each no more than 20% above
  `main`.

The evidence report includes exact counts and denominators, overall and
platform/family breakdowns, failure examples, reproduction commands,
limitations, and a Better Askman or inconclusive recommendation.

Otherwise the result is inconclusive.

## Amendment (2026-09-20, pre-registered before any holdout access): one-sided superiority interval

The paired-bootstrap condition is refined before the release gate runs on the
`evaluation-v2` holdout split. The claim under test is superiority
(`retrieval-v2` is at least as good and better on the primary metric), so the
bootstrap condition becomes:

- A fixed-seed, 10,000-resample paired bootstrap of the overall paired
  `Success@1` gain has a **one-sided 95% lower bound above zero**. The seed is
  recorded in the evidence report. The two-sided interval is still reported.

Motivation: on 30-answerable-task splits the two-sided 95% interval puts its
entire error budget on both tails; a genuinely better candidate with few
paired flips can fail "wholly above zero" while every other condition passes.
Development-split measurement (2026-09-20): +16.7 paired `Success@1` points
with a two-sided 95% interval of [0.0, +33.3pp] and a one-sided lower bound of
roughly +4.4pp. This amendment changes only the interval interpretation; the
five-point absolute `Success@1` gain requirement, the per-family and safety
conditions, the resource limits, and the offline checks are unchanged.

## Clarification (2026-09-26): evaluate holdout guardrails separately

For a candidate selected on development tasks, development results cannot
offset a holdout regression. Report split results separately; promotion needs a
holdout `Success@1` gain of at least five percentage points with a one-sided
95% paired-bootstrap lower bound above zero. Holdout `Success@3`, incorrect-
answer rate, and false-answer rate must not regress overall or by platform;
`Success@1` and `Success@3` must not regress on any platform. Offline execution
must succeed, and fresh-process p95 and peak memory for each split plus warmed
p95 and peak memory keep the 20% limits. Combined counts remain descriptive
and cannot establish independent improvement on their own.

The canonical runner now records a separate independent-holdout decision and
includes it in the release recommendation. It also rejects a fresh holdout
whose frozen manifest or dataset digest differs from the reviewed freeze.
Resource limits apply to every measured phase, and fresh-process memory
measurements are required.

The authorized focused-candidate run on fresh holdout v1 measured a +2/30
`Success@1` gain, but its one-sided 95% paired-bootstrap lower bound was
−3.3 percentage points. `Success@3` fell from 19/30 to 15/30, and incorrect
answered tasks rose from 7/26 to 10/25. The canonical decision is
`inconclusive`; do not promote this candidate or tune from the consumed split.
The release-readiness validator also rejected it because the independent
holdout bootstrap lower bound was not positive. The preserved report is
[`main-vs-retrieval-v2-focused-fresh-holdout-v1.json`](../reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v1.json).
