# Description embedding A/B — dev v1 protocol

Frozen before either arm was scored on 2026-09-27. Development evidence only;
this run does not authorize a release or any holdout access.

## Question

Does embedding only each operational example's own description improve correct
first results over the main-compatible text recipe, while preserving top-three
usefulness, answer safety, platform behavior, offline execution, latency, and
memory?

## Fixed inputs

- Dataset: `tests/fixtures/evaluation/dev-description-v1.json`, SHA-256
  `75299048c05b77a8445d77cc6a6e67735fd3c1b7b653d9c4422fcc476157c542`.
  Freeze: `tests/fixtures/evaluation/dev-description-v1.manifest.json`, SHA-256
  `2871155f4a72095cbeab8ad70bd6b426ebfdbf53bb56cdb0a002a8a667b67065`.
- 60 tasks: 30 answerable and 30 abstain; 12 scenario families; 15 tasks per
  platform. Labels were source-audited before retrieval. The audit used the
  same questions and labels; only dataset/cohort/freeze/provenance metadata
  changed after its recorded input digest.
- Corpus: parser v4, pinned tldr revision and manifest. Both bundles validate
  and expose 142 identical visible examples with inventory digest
  `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Both bundles use the same MiniLM model, model revision, runtime, CLI version,
  source pages, platform routing, and example records. Control bundle
  `matching-bundle-v2:8e53794515abdcaa0e304fb3ea533144461ae7018f87264c2fabcbd3fee191e4`
  has manifest SHA-256 `e61b2a4fbb6f3fae2c6f80674fb714b3b1a6694b7e1c74c2dc131be485110cce`
  and database SHA-256
  `a98f2d828c292587270b4366fd3be5c94cd56a8237a71070c0fe883b3ccf520b`.
  Treatment bundle
  `matching-bundle-v2:de6eda0ad301460e89606327a5af2d798317e05d7ff06498a7ec5e94b9b21574`
  has manifest SHA-256 `79861dd297fb04082beab4635267d632cf2582b4222785603b5df9e4fbf50f4b`
  and database SHA-256
  `79e4ae3171dfd41079b322943df59ad40e2185b3e878174ca39b26505eb2de65`.
- Reference behavior: the installed-main CLI/data pair provisioned at
  `/tmp/askman-goal.Fk5Zkh/main-import-home/Library/Application Support/askman`.
  The canonical runner records its database, model, binary, and report digests.

## Single changed factor

Control config `dev-description-v1-control-main-compatible.json` (SHA-256
`c6b04a864cdabfd228339dc534249a416fee1b545794fd82c7a101c4eee3cf85`) uses the
main-compatible dense text recipe. Treatment config
`dev-description-v1-treatment-description.json` (SHA-256
`fe8826603e598e005058a2037569974cdbbebb90528bc8d268a71a6e062a9cfff`) uses
`description`, which embeds only the example description. The configs differ
only in `configuration_id` and `dense_recipe`.

Everything else is fixed: focused-v2 query rules, candidate budget 8,
same-page selection, raw cosine cutoff 0.60, lexical rerank weight 0.05,
scoped guards, and display limit 3. This is an end-to-end representation
comparison: the recipe changes both candidate ordering and distances evaluated
by the fixed cutoff. No thresholds or rules will be tuned from these results.

## Run and decision rules

Run each frozen config once through `scripts/run_release_gate.py` with
`--dev-only --allow-custom-dev-dataset`. The gate network-denies query
processes and measures fresh-process and warmed latency and memory. It reads no
holdout dataset, labels, or result reports. The release-gate output is expected
to remain inconclusive because dev-only evidence cannot approve release.

Compare the two candidates on the same 60 tasks and separately report each
against installed main. A development candidate is promising only if correct
Success@1 improves and Success@3, false answers, incorrect answered tasks,
platform results, offline operation, and resource limits meet the frozen gate
guardrails. This result is not independent validation. Any later holdout
scoring requires a new unseen split and explicit authorization.
