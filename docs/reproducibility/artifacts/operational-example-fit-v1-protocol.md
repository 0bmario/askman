# Operational example fit v1

## Question

Does checking explicit requested actions and constraints against each retrieved example improve correct first results, with retrieval otherwise fixed?

## Frozen inputs

- Development cohort: `askman-operational-compatibility-dev-v1`, 60 prompts across 12 families.
- Independent source audit: 28 supported prompts with one exact example each; 32 rejected prompts. This is independent labeling, not independent candidate validation.
- The author draft planned 30/30. The blind source audit is authoritative; the author labels are preserved but not used.
- Corpus: manifest-v4, 24 pages and 142 operational examples, source revision `e1cb966e711d73c42d75e79834be7e4dc17264ef`.
- The audit input mislabeled the source digest as the manifest file SHA. The frozen dataset corrects this metadata to the literal manifest SHA. Prompts and labels are unchanged; raw inputs and the audit record are preserved.
- Final freeze manifest: `operational-compatibility-dev-v2-freeze.json`.
- The v1 freeze manifest and dataset remain preserved as unscored preflight artifacts. Preflight exposed a validator treating `manifest_path` as DB metadata. The validator now treats it as a locator; v2 freezes the corrected scorer and corpus checks. No CLI retrieval ran under v1.

## One-factor comparison

Control and treatment use the same main-compatible dense recipe, focused-v2 query mode and rewrites, candidate budget, raw distance cutoff, lexical reranking, platform selection, abstention guards, corpus bundle, and display limit.

- Control: `operational-example-fit-v1-control-config.json`; source-backed check off.
- Treatment: `operational-example-fit-v1-treatment-config.json`; source-backed check on.
- Treatment filters eligible examples after the existing distance cutoff and before the unchanged ranking and top-three truncation. Its evidence is limited to the example description, example command, and page command. Page overview text is excluded.
- No query rewrites, embedding, ranking weights, cutoff, candidate pool, or platform rules change between control and treatment.

## Decision criteria

Prefer the treatment only if it raises correct Success@1 versus the control and has no required regression in Success@3, false answers, platform behavior, offline execution, latency, or peak memory. A dev-only gate cannot authorize release. If this experiment misses, preserve the result and use a fresh development cohort for another approach; do not retune on these scored prompts.

## Scope

Only the new development cohort is scored. Holdout labels and query-level outputs are not accessed. Any later holdout scoring requires fresh explicit authorization and a new frozen candidate; no tuning may use holdout results.
