# Dense candidate budget v1 — frozen protocol

## Question

Does expanding the main-compatible dense candidate pool from 8 to 16 improve correct first results on a fresh, source-backed operational development cohort?

## Cohort and corpus

- 60 fresh prompts in 12 opaque scenario families × 5 tasks, with 15 prompts per platform.
- Independent source audit: 26 answerable and 34 unsupported. Raw prompt pool, label output, and audit are preserved beside this protocol. Labels require one individual operational example to cover the requested operation; documentation redirects do not count.
- Corpus: manifest-v4, parser `tldr-subset-v4`, source revision `e1cb966e711d73c42d75e79834be7e4dc17264ef`, source digest `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`, manifest SHA-256 `3548a0b5b4190c144354f1ee7cc505bdae3c3c877a7d409bb32a94900c637b85`.
- Freeze dataset, labels, protocol, configs, candidate-source digests and zero prior gate runs before scoring. Preserve all frozen inputs.

## One-factor comparison

Run the canonical release gate twice with `--dev-only --allow-custom-dev-dataset`, the same candidate source tree, pinned bundle and corpus records. Main source-build is reported separately by each gate run. Network denial remains enabled.

- Control: `dense-budget-dev-v1-control-config.json`, dense candidate budget 8.
- Treatment: `dense-budget-dev-v1-treatment-config.json`, dense candidate budget 16.
- Change only the candidate budget. Keep embeddings and dense recipe, query rules, platform selection, lexical rerank, raw cutoff, same-page selection, abstention guards, top-three display, corpus, examples, and source tree fixed. No query-level tuning or other factor changes.
- This checks final Success@1 and Success@3, not candidate recall alone.

## Decision rule

Retain 16 only if, against both the 8-candidate control and source-built main on these same pinned records:

1. Supported-task Success@1 gains at least 2 tasks over each reference.
2. Aggregate and per-platform Success@3 do not fall; per-platform Success@1 does not fall.
3. Coverage does not fall; false answers on unsupported tasks and incorrect answers on supported tasks do not increase.
4. Network-denied runs have zero CLI failures, and fresh/warm p95 latency and peak memory stay within 20% of each reference.

Otherwise reject 16. No thresholds, weights, queries, labels, or configurations will be changed after examining this cohort. A dev result is not independent validation or release authorization. If the candidate passes, freeze a new unseen holdout and ask for explicit authorization before scoring it. Do not tune on holdout results.
