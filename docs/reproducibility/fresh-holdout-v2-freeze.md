# Fresh holdout v2 freeze

Frozen 2026-09-26T18:24:29Z. Status: **unscored**. Candidate commit
`ba74692cf79fa9c294f685fbade8f9315aeacdd1` is the intended evaluation target.
No candidate or release gate has accessed this split. Get explicit user
authorization before scoring it.

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

## Scoring state

The split is frozen and unscored. Both candidate and release-gate run counts
are zero. Do not open it with a candidate until the user explicitly authorizes
one canonical run.
