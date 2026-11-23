# Fresh holdout v2 freeze

Frozen 2026-09-26T18:24:29Z. At freeze time, status was **unscored**.
Candidate commit `ba74692cf79fa9c294f685fbade8f9315aeacdd1` was the intended
evaluation target. The candidate was later evaluated once after explicit user
authorization. Frozen inputs remain unchanged; manifest counters preserve
freeze-time state.

## Contents and provenance

- 60 tasks: 30 answerable and 30 abstention tasks; 15 per platform.
- 60 unique task families selected from an 80-prompt pool.
- Corpus: tldr-pages revision `e1cb966e711d73c42d75e79834be7e4dc17264ef`,
  parser `tldr-subset-v4`, 142 visible examples.
- Corpus source digest:
  `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Corpus manifest SHA-256:
  `3548a0b5b4190c144354f1ee7cc505bdae3c3c877a7d409bb32a94900c637b85`.
- Prompt pool SHA-256:
  `53d9ecab5d835a8723a2abda3f8b85b687cb7275e813ce1a1a9181512a61feab`.
- Final dataset SHA-256:
  `8019c67c7ff13f6a9d06159ea0cf12cc3914011c69686fa2b5c93270f879797d`.
- Freeze manifest SHA-256:
  `c45464cf3591a49372ef1a455648e7e03b3849b7798c8d1b5d0cdd4daec5d4cb`.

Prompts were frozen before a separate label audit. The audit mapped acceptable
IDs to the pinned parser-v4 records and assigned abstention labels without
running retrieval or viewing candidate outputs. Structural checks, exact
source-ID validation, and disjointness from the default development split
passed. Per-platform answerable/abstain counts are common 7/8, Linux 6/9,
macOS 9/6, and Windows 8/7.

The dataset and freeze manifest are
[`fresh-holdout-v2.json`](../../tests/fixtures/evaluation/fresh-holdout-v2.json)
and
[`fresh-holdout-v2.manifest.json`](../../tests/fixtures/evaluation/fresh-holdout-v2.manifest.json).
The prompt-only authoring pool is preserved at
[`fresh-holdout-v2-prompts.json`](../../tests/fixtures/evaluation/fresh-holdout-v2-prompts.json).

## Scoring record

The split was scored once against main by the canonical release gate, using
candidate ba74692cf79fa9c294f685fbade8f9315aeacdd1. Holdout Success@1 was
12/30 to 15/30 and Success@3 13/30 to 17/30. Incorrect answered tasks were
9/22 to 3/20; false answers tied at 5/30. The one-sided 95% paired-bootstrap
lower bound was 0.0; common-platform Success@3 regressed. The independent
decision is inconclusive. The split is consumed and must not be reused or used
to tune a candidate.

The complete paired report is
[main-vs-retrieval-v2-focused-fresh-holdout-v2.json](artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v2.json)
with a
[rendered report](artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v2.md).
The frozen dataset, prompt pool, and manifest were not changed.
