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

## Amendment (2026-09-26): fresh holdout v2 frozen and scored once

A new 60-task holdout was authored and frozen for candidate
`ba74692cf79fa9c294f685fbade8f9315aeacdd1`. It uses the parser-v4 142-record
corpus, has 30 answerable and 30 abstention tasks, 15 per platform, and is
disjoint from the default dev split. Prompts were frozen before a separate
source-ID label audit. After explicit user authorization, the candidate was
scored once by the canonical gate. Holdout Success@1 improved 12/30 to 15/30
and Success@3 13/30 to 17/30; false answers tied at 5/30. The one-sided 95%
paired-bootstrap lower bound was zero, and common-platform Success@3
regressed, so the independent decision is inconclusive. The split is
consumed; do not tune from or reuse it. Dataset SHA-256 is
`8019c67c7ff13f6a9d06159ea0cf12cc3914011c69686fa2b5c93270f879797d`; freeze
manifest SHA-256 is
`c45464cf3591a49372ef1a455648e7e03b3849b7798c8d1b5d0cdd4daec5d4cb`. The
canonical runner and readiness validator pin this freeze. Frozen inputs
remain unchanged; manifest status records freeze-time state. The split is
consumed. Require a new unseen split and explicit authorization before
evaluating another candidate. Full provenance and scoring record are in
[`fresh-holdout-v2-freeze.md`](../reproducibility/fresh-holdout-v2-freeze.md).

## Amendment (2026-09-27): source-audited Description cohort

A new 60-task development cohort was authored and labeled against the pinned
parser-v4 source pages and exact operational example IDs before retrieval. It
has 30 answerable and 30 abstention tasks, 12 families, and 15 tasks per
platform; the family audit covers 24 pages and all 142 indexed examples. Its
dataset SHA-256 is
`df691502e66e851b3ad20d090c05085ddffe16072851731133f405ae2541ec7c`; freeze
manifest SHA-256 is
`d57c7aaf8dfad686c73e551090b0346b97ca2949d7eedae2ca683e95f10d1cb4`.

Two earlier freeze attempts are preserved but were not scored: one lacked the
pinned parser-manifest path, and one used unregistered schema identity values.
The final freeze corrected those fields without changing task rows. The
canonical runner validates this custom schema-3 cohort only under
`--dev-only`; holdout access still requires explicit authorization. The
Description A/B is development evidence only and does not establish
independent improvement. See the [cohort audit](../reproducibility/artifacts/dev-description-v1-label-audit.json)
and [A/B comparison](../reproducibility/artifacts/description-embedding-dev-v3-comparison.md).

## Amendment (2026-09-27): query rewrite development candidate

The frozen `askman-dev-extension-v1` cohort identified two source-backed gaps:
file-extension search and Windows cross-drive moves. A controlled ablation
isolated each rewrite and their combination on the same 142 parser-v4 records.
The combined mode measured 22/30 Success@1, 27/30 Success@3, and 0/30 false
answers; focused-v1 measured 15/30, 22/30, and 0/30. The exact paired CLI gate
against installed main measured 13/30→22/30 Success@1 and 21/30→27/30
Success@3. These rules were selected using this development cohort, so the
result is exploratory and cannot count as independent validation. The
original development split was rerun as a regression check; it is previously
inspected development data. Neither consumed holdout can be reused. At this
stage, fresh holdout v3 was frozen and unscored pending explicit authorization;
its later result is recorded below.
See
[`focused-query-rewrites-dev-extension-v1-native-platform.md`](../reproducibility/artifacts/focused-query-rewrites-dev-extension-v1-native-platform.md)
and the paired gates linked from the approach review.

## Amendment (2026-09-27): fresh holdout v3 scored once

After explicit user authorization, the focused query-rule candidate was
compared once with installed main on the frozen v3 dataset and pinned corpus.
Holdout Success@1 improved 12/30→18/30 and Success@3 16/30→22/30; false
answers tied at 0/30. The holdout bootstrap lower bound was 6.7 pp. However,
common-platform Success@3 fell 5/8→4/8 and incorrect answered tasks rose
1/6→1/5, so the release gate remains inconclusive. This split is consumed;
do not tune from or reuse it. The freeze manifest remains unchanged, with its
counters describing freeze-time state. See the
[v3 freeze and score record](../reproducibility/fresh-holdout-v3-freeze.md)
and the [canonical report](../reproducibility/artifacts/main-vs-retrieval-v2-focused-query-rules-fresh-holdout-v3.md).
Any later independent evaluation requires a new unseen split and explicit
authorization.

## Amendment (2026-09-27): operational-compatibility development schema

The runner now accepts a registered schema-4 development-only cohort for
source-backed operational prompts. This cohort has 60 tasks, 12 families,
and 15 tasks per platform; its independent source audit labels 28 supported
and 32 unsupported prompts. Family groups may mix platforms and answerability,
so schema 4 validates family size and split isolation without requiring the
schema-3 30/30 label balance. It remains limited to `--dev-only` and cannot
authorize release or access holdout labels.

Frozen dataset SHA-256:
`ab34155b640eb1227df53cc8e7ad3e5c034b71b2aa65f85670fa4f9b99b0c964`.
Freeze manifest SHA-256:
`4019229886e09a7e70ac07b587b57740380cbdfae3616019a25e3236aace869f`.
The earlier v1 preflight freeze remains preserved but unscored; v2 is the
registered freeze used by the one-factor experiment. Prompt text and blind
labels were retained; only the corpus manifest SHA metadata was corrected to
the literal manifest-file digest. The label audit is independent labeling,
not independent candidate validation. See the
[experiment comparison](../reproducibility/artifacts/operational-example-fit-v1-comparison.md)
and [freeze provenance](../reproducibility/artifacts/operational-compatibility-dev-v2-freeze.json).

## Amendment (2026-09-27): fresh soft-fit development cohort

A new 60-task source-backed development cohort was authored for the bounded
soft-fit experiment. It has 12 new families, 15 prompts per platform, and 29
answerable / 31 unsupported labels after an independent source-only
adjudication. The adjudication rejected a numeric in-place sort task because
no individual example covered both operations; the raw audit and correction
remain preserved. The pinned parser-v4 corpus has 24 pages and 142 operational
examples. Dataset SHA-256 is
`418ac923013146d3b60d920aba50a5d9f69afd3da1c658495c226b648a772daa`; freeze
manifest SHA-256 is
`093aefd39bc81f91fb66a99322d0e761d7eabbb51589639ebcfd57bab0607ac1`.

The canonical runner accepts this registered schema-4 custom cohort only with
`--dev-only`. Control and treatment ran on identical corpus records; no
holdout dataset, labels, or query outputs were accessed. Both reports are
development-only and cannot approve release. See the [comparison](../reproducibility/artifacts/operational-soft-fit-dev-v1-comparison.md),
[freeze](../reproducibility/artifacts/operational-soft-fit-dev-v1-freeze.json),
and [label audit](../reproducibility/artifacts/operational-soft-fit-dev-v1-label-audit-raw.json).

## Amendment (2026-09-27): dense-budget development evaluation

The schema-4 operational development format was used for a new 60-prompt,
12-family cohort with 26 answerable and 34 unsupported labels. The fresh
blind source audit and exact example IDs were frozen before retrieval. Its
canonical control and treatment runs used the same pinned corpus records and
`--dev-only`; no holdout was read or scored. The wider-budget treatment tied
the control, so budget 8 remains the setting. This is development evidence,
not independent validation. The result cohort is fully inspected and is
closed to further tuning. Frozen artifacts and the build-hash correction are
linked from the [comparison](../reproducibility/artifacts/dense-budget-dev-v1-comparison.md).
