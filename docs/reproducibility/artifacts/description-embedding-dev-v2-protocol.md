# Description embedding A/B — dev v2 protocol

Frozen before retrieval on 2026-09-27. It supersedes the unscored v1 freeze;
the initial gate attempt stopped at structural validation because
`corpus.manifest_path` was missing. No task rows or CLI queries were accessed.
The v1 dataset, manifest, and protocol remain preserved. The v2 task rows are
identical; only dataset/freeze identity and corpus manifest-path metadata were
corrected.

## Frozen inputs

- Dataset: `tests/fixtures/evaluation/dev-description-v2.json`, SHA-256
  `ad65696169b3f8b3895f28107d31db1e9c3783bb8372e6eff7a0c442a8f77e75`.
- Freeze manifest: `tests/fixtures/evaluation/dev-description-v2.manifest.json`,
  SHA-256
  `305816f7916f906431c04be0034c10c889cf5799ffb62368f2f356b3d2798c07`.
- 60 development tasks: 30 answerable, 30 abstain; 12 families; 15 tasks per
  platform. Labels and source IDs were audited before retrieval in
  `dev-description-v1-label-audit.json`. The checked-in prompt intent record is
  `dev-description-v1-prompt-authoring.json`.
- Corpus manifest: `tests/fixtures/tldr-evaluation-v2/manifest-v4.json`, SHA-256
  `3548a0b5b4190c144354f1ee7cc505bdae3c3c877a7d409bb32a94900c637b85`.
  Both parser-v4 bundles validate and expose the same 142 visible records,
  inventory digest
  `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Control config SHA-256:
  `c6b04a864cdabfd228339dc534249a416fee1b545794fd82c7a101c4eee3cf85`.
  Treatment config SHA-256:
  `fe8826603e598e005058a2037569974cdbbebb90528bc8d268a71a6e062a9cfff`.
  They differ only in `configuration_id` and `dense_recipe`.
- The installed-main data and CLI pair is the reference for each arm. Runtime,
  model revision, platform routing, query rules, ranking, guards, corpus
  records, and evaluation tasks are fixed.

## Comparison

Control uses the main-compatible embedding text. Treatment uses only the
example description. Keep focused-v2 query rules, dense top-8, same-page
selection, raw distance cutoff 0.60, lexical rerank weight 0.05, scoped
negation/unsupported-intent guards, and display limit 3 fixed. This tests the
end-to-end representation recipe because it affects both dense ordering and
the fixed cutoff's distance geometry.

Run the canonical gate once per arm with `--dev-only
--allow-custom-dev-dataset`; queries are network-denied. Do not inspect or
score any holdout. Compare candidate arms on the same tasks and report each
against installed main. Require a correct-first-result gain with no required
regression in top-three usefulness, false/incorrect answers, platform
behavior, offline execution, latency, or memory. Do not tune after seeing
results. Dev results are not independent validation and cannot promote a
release. Any later holdout score requires a new unseen split and explicit
authorization.
