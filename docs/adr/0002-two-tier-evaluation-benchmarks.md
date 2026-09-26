# Two-tier retrieval evaluation

Keep `evaluation-v1` immutable as a small regression benchmark. Create
`evaluation-v2` with exactly 120 new tasks:

- 60 development tasks and 60 hidden holdout tasks;
- exactly 30 answerable and 30 unanswerable tasks in each split; and
- all four target platforms: `common`, `linux`, `osx`, and `windows`.

Use scenario families for grouping and keep each paraphrase family within one
split.

Record benchmark provenance for every task: a public, license-compatible user
intent, stable ID, and rationale. Exclude private data and copied candidate
answers. Authors must author and freeze prompts before inspecting retrieval
outputs.

Labels are relative to the pinned corpus and requested platform: an answerable
task has at least one acceptable corpus example, while an unanswerable task has
none. Tune only on development tasks and freeze the retrieval configuration
before opening holdout results.

## Amendment (2026-09-26): parser-version compatibility

Frozen evaluation-v2 labels remain pinned to parser v3. A candidate using a
different parser may use those labels only when the canonical gate rebuilds the
frozen corpus with the recorded parser-v3 reference and proves exact equality
of stable example IDs, page IDs, platforms, commands, and visible descriptions.
Any record difference fails compatibility. Keep the v3 manifest and datasets
immutable; version candidate inputs separately, such as
`tests/fixtures/tldr-evaluation-v2/manifest-v4.json`. This check reads no
holdout labels in dev-only mode and does not authorize holdout evaluation.

## Amendment (2026-09-26): authorized holdout result

The earlier dense-only candidate was run once through the canonical
gate against the frozen holdout. Development improved, but holdout
`Success@1` tied main at 19/30 and `Success@3` fell from 25/30 to 20/30. The
candidate is not promoted. Do not tune from this result or reuse this holdout
to evaluate a later candidate. A future independent claim needs a fresh,
unseen holdout.

Before this run, broad searches accidentally surfaced one frozen holdout row
and snippets from existing holdout evidence. They were not used for tuning,
but the run is not fully blind and must be described with that limitation.
The authorized gate report is
[`main-vs-retrieval-v2-authorized-v1.json`](../reproducibility/artifacts/main-vs-retrieval-v2-authorized-v1.json).

## Amendment (2026-09-26): fresh independent holdout

Because evaluation-v2's holdout is consumed, a separate 60-intent holdout was
authored and frozen against the same 142-record parser-v4 corpus. It has 30
answerable and 30 abstention tasks, 15 per platform, and unique task IDs and
families. Independent prompt-only labeling plus source-ID verification is
recorded in the freeze artifacts. Dataset SHA-256 is
`7fe11e153b64941c91233b756543487ebdd34e17bcca7b935a55f8f16a6fb2a0`; freeze
manifest SHA-256 is
`7463ccb782cf971b4893f369c899f408212306020c68e471b72c146b2da68f1a`.

The split was scored once by the canonical gate after explicit authorization,
against candidate commit `3494a11c57c31045bb9897c9fa187d768e18ebcb`. It is
now consumed. The candidate gained 2/30 `Success@1`, but the one-sided 95%
paired-bootstrap lower bound was −3.3 points; `Success@3` fell 19/30→15/30
and incorrect answered tasks rose 7/26→10/25. The decision is inconclusive;
do not tune on or reuse this split. The frozen dataset and manifest remain
byte-for-byte unchanged; their status fields record the freeze-time state.
The complete post-freeze result is
[`main-vs-retrieval-v2-focused-fresh-holdout-v1.json`](../reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v1.json).
Require explicit authorization before scoring any future holdout. The freeze
process and label audit are recorded in
[`fresh-holdout-v1-freeze.md`](../reproducibility/fresh-holdout-v1-freeze.md).

## Amendment (2026-09-26): new development-only cohort

The original development split is saturated from repeated candidate work. A
separate 60-task dev-only cohort was authored and frozen before any retrieval
run. It has 12 new scenario families, 30 answerable and 30 abstention tasks,
15 tasks per platform, and uses the pinned 142-record parser-v4 corpus. Dataset
SHA-256 is
`6c113bed013be3f532a8287c58a4f257347585c2be963d6c3b475d41ecc49905`; freeze
manifest SHA-256 is
`9dcf13de29e6b0969344e6b2c64b298f9550ac320dad67dfca4a8a9ad9a096d5`.

This cohort is development evidence only. Its frozen labels are validated
against the pinned corpus. Custom-cohort support in the canonical runner is
restricted to `--dev-only`; it cannot score holdout or recommend release.
The selected candidate gained 2/30 Success@1 tasks over main with no measured
top-three, answer-safety, platform, offline, latency, or memory regression,
but the one-sided 95% paired-bootstrap lower bound is zero. Keep main shipped.
Any independent claim needs another unseen holdout and fresh explicit
authorization before scoring; neither consumed holdout is reusable.
