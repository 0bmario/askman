# Fresh holdout v3 freeze

Frozen 2026-09-26T23:07:00Z for the focused-v2 query-rule candidate. The
freeze-time status was **unscored**. The inputs below remain immutable after
the one authorized score recorded below.

## Inputs and provenance

- 100 prompt-only candidates, 25 per platform; SHA-256
  `dbb07784cab867d9e20a0328199a1484f466aef4d2c36e5ea14704e35d5dee77`.
- Final dataset: 60 tasks, one per unique family, 30 answerable and 30
  abstain; SHA-256
  `b4f25cccf30f5b05232c09d6b1c91e0b914b82e206edb9256a74847b7ed4450d`.
- Freeze manifest SHA-256:
  `0b8e0c1b96cd68f0bccd86de34c2edc4150a370666808aa4b90dc9ae7812e89a`.
- Corpus: 142 visible examples, `tldr-subset-v4`, revision
  `e1cb966e711d73c42d75e79834be7e4dc17264ef`, digest
  `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Separate label audit mapped answerable prompts to exact IDs in the pinned
  matching database and checked platform eligibility. Unsupported tasks have
  empty acceptable-ID lists. All 60 labels passed those checks.
- Task IDs, families, and questions are disjoint from the four checked dev
  datasets. Distribution: common 8/7 answerable/abstain; Linux 7/8; macOS
  8/7; Windows 7/8.
- The pool includes supported extension-search prompts and five Windows
  cross-drive move prompts. Four macOS Spotlight suffix searches are labeled
  unsupported because the pinned page does not show wildcard or extension
  matching.
- No retrieval or candidate output was inspected during final prompt
  authoring or labeling.
- A preliminary draft was discarded after its author opened a prior score
  summary; none of that draft's prompts or labels were reused.

The frozen inputs are
[`fresh-holdout-v3-prompts.json`](../../tests/fixtures/evaluation/fresh-holdout-v3-prompts.json),
[`fresh-holdout-v3.json`](../../tests/fixtures/evaluation/fresh-holdout-v3.json),
and
[`fresh-holdout-v3.manifest.json`](../../tests/fixtures/evaluation/fresh-holdout-v3.manifest.json).
The canonical runner and release-report validator pin the dataset and manifest
hashes. Freeze ID: `fresh-holdout-v3-freeze-2026-09-27`.

## Freeze-time scoring status

- Candidate binary SHA-256:
  `e727941c9efbfadc0ba4bd89885d880d8f3b6ca27d663f88c502e89c4d91e1b5`.
- Candidate runs on this split: 0.
- Release-gate runs on this split: 0.
- The freeze manifest preserves these zero counters as freeze-time metadata.

## Authorized score (2026-09-27)

After explicit user authorization for one run, the canonical release gate
compared the working-tree candidate against installed main on the identical
142-record corpus. The run is recorded in
[`main-vs-retrieval-v2-focused-query-rules-fresh-holdout-v3.md`](artifacts/main-vs-retrieval-v2-focused-query-rules-fresh-holdout-v3.md)
and its JSON companion. The holdout improved Success@1 from 12/30 to 18/30
and Success@3 from 16/30 to 22/30; false answers tied at 0/30. The one-sided
95% paired-bootstrap lower bound on holdout Success@1 gain was 6.7 pp.

The release gate remains **inconclusive**. On common-platform holdout tasks,
Success@3 fell 5/8 to 4/8 and incorrect answered tasks rose 1/6 to 1/5. It
also found a negative Success@1 family
(`fresh-v3-clean-common-find-ext-markdown-notes`, 1/1 to 0/1). The canonical
readiness validator failed on the common-platform Success@3 regression.
Network-denied execution had zero CLI failures; measured latency and memory
passed their limits. Installed main remains the shipped product.

This holdout is **consumed**. Do not tune from its aggregate, platform, or
task-level results, and do not score it again. A later candidate needs a new
unseen holdout and fresh explicit authorization before scoring. The frozen
prompt pool, dataset, and manifest hashes above were not changed by evaluation.
