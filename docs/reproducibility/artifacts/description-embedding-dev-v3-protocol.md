# Description embedding A/B — dev v3 protocol

Frozen before retrieval on 2026-09-27. The v1 and v2 freeze attempts failed
structural validation before retrieval; no CLI queries or candidate outputs
were produced. Their datasets and manifests remain preserved. V3 keeps the
same 60 task rows and restores the registered schema-3 identity while adding
the required corpus manifest path.

## Frozen inputs

- Dataset: `tests/fixtures/evaluation/dev-description-v3.json`, SHA-256
  `df691502e66e851b3ad20d090c05085ddffe16072851731133f405ae2541ec7c`.
- Freeze manifest: `tests/fixtures/evaluation/dev-description-v3.manifest.json`,
  SHA-256
  `d57c7aaf8dfad686c73e551090b0346b97ca2949d7eedae2ca683e95f10d1cb4`.
- Tasks: 60 development tasks, 30 answerable and 30 abstain, 12 families, 15
  per platform. Labels and source IDs were audited before retrieval in
  `docs/reproducibility/artifacts/dev-description-v1-label-audit.json`; the
  prompt intent record is `dev-description-v1-prompt-authoring.json`.
- Corpus manifest: `tests/fixtures/tldr-evaluation-v2/manifest-v4.json`, SHA-256
  `3548a0b5b4190c144354f1ee7cc505bdae3c3c877a7d409bb32a94900c637b85`. Both
  parser-v4 bundles validate and expose 142 identical visible records with
  inventory digest
  `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Control config SHA-256:
  `c6b04a864cdabfd228339dc534249a416fee1b545794fd82c7a101c4eee3cf85`.
  Treatment config SHA-256:
  `fe8826603e598e005058a2037569974cdbbebb90528bc8d268a71a6e062a9cfff`.
  They differ only by `configuration_id` and `dense_recipe`.
- Both arms use the installed-main CLI/data as reference. Model, runtime,
  corpus records, platform routing, focused-v2 query rules, and other retrieval
  behavior stay fixed. Embeddings use
  `Qdrant/all-MiniLM-L6-v2-onnx@5f1b8cd78bc4fb444dd171e59b18f3a3af89a079`
  with `fastembed-4.8.0`; CLI compatibility is `askman=0.3.3`.

## Comparison and decision rule

Control uses main-compatible dense text. Treatment uses only the example
description. Both use dense top-8, same-page selection, raw distance cutoff
0.60, lexical rerank weight 0.05, scoped negation and unsupported-intent
guards, and display limit 3. Representation changes both dense ordering and
the fixed cutoff's distance geometry; no thresholds or rules will be tuned
from results.

Run the canonical gate once per arm with `--dev-only
--allow-custom-dev-dataset`. Query processes are network-denied. The gate reads
only the base benchmark freeze manifest metadata; it does not read holdout
datasets, labels, reports, or results. Compare both
candidates on the same tasks and report each against installed main. A
development candidate needs higher correct Success@1 and no required
regression in Success@3, false or incorrect answers, platform behavior,
offline execution, latency, or memory. Dev evidence cannot approve a release.
Any future holdout scoring needs a new unseen split and explicit authorization.
