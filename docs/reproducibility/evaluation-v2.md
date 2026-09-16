# Frozen evaluation-v2 release benchmark

Issue #30 freezes the benchmark for the later `main` versus `retrieval-v2`
release gate. `evaluation-v1` remains the small regression benchmark; it is
not release evidence.

Issue #39 adds the versioned, broader corpus-backed freeze in
[`evaluation-v2-expanded.md`](evaluation-v2-expanded.md). This document remains
the original `evaluation-v2` protocol freeze.

## Frozen inputs

The checked-in freeze record is
`tests/fixtures/evaluation/evaluation-v2-manifest.json`. It binds:

- Dataset: `askman-evaluation-v2`, schema `2`, scorer `task-scorer-v1`.
- Split: `scenario-family-split-v2`; 60 development and 60 holdout tasks.
- Balance: 30 answerable and 30 unanswerable tasks per split.
- Families: 12 complete five-task families per split; family names and task IDs
  are disjoint between splits.
- Platforms: 15 tasks each for `common`, `linux`, `osx`, and `windows` in each
  split.
- Corpus: `fixture-tldr-full-corpus-v1:d93ffff3c216b85caabdec2a36c6f20a9107526a32143a7bb2cc086dc77d5822`.
- Corpus manifest SHA256:
  `68ae06300afdaee1515ef7c6248f35056e871e73d07778f2e1c2f636589c8461`.
- Freeze manifest SHA256:
  `f517343a047cb9a6c36b6d15d13425dc54a49b6e4c26e20bbffd61e955819921`.

Input SHA256 values:

| Input | SHA256 |
| --- | --- |
| `frozen-dev-v2.json` | `0c82627a899c65bcfede704be04d4cabd8b424f7317fadbd2c30a44e03305d8d` |
| `frozen-holdout-v2.json` | `c64b40aaca8476c2ea0019a8b6bd9b9e6d11a7865169bb7c5d934a6e3c8280ab` |
| `task-intents-v2.json` | `d29f296152632e7dda89f2927213408142a272a04b600f100577c3b366071920` |
| `scripts/evaluate_retrieval.py` | `006f934dc6e7cb251776bdb8090a014ae0c749e2b976d306b58623e01613ec90` |

Validate the complete freeze without an artifact or network:

```sh
python3 scripts/validate_evaluation_v2.py
```

## Authoring and adjudication

`tests/fixtures/evaluation/task-intents-v2.json` is the intent record. Its
source catalog points to the public MIT-licensed `tldr-pages` project. Each
task records only a source category and normalized intent. The intent freeze
records that authoring happened before retrieval-output inspection; no private
prompts or copied candidate answers are present.

Questions, labels, rationales and acceptable IDs live in the separate split
files. They are not part of the corpus snapshot or retrieval indexes. Labels
were adjudicated after intent freeze against the pinned matching-bundle corpus
identity and requested platform. A positive label contains one or more stable
source example IDs; an unanswerable label contains an empty list. The evaluator
supports multiple acceptable IDs when behaviors genuinely overlap and scores
the displayed example ID, not the command name alone.

Hand-checked scorer cases are kept in `tests/test_evaluation_runner.py` for
multiple valid IDs, a wrong example under the right command, no result, and
false answers on unanswerable tasks.

The committed fixture has five operational examples, so this benchmark freezes
the protocol and comparison inputs rather than claiming production retrieval
quality. Larger source-backed corpus coverage is a separate quality concern.

## Development and holdout access

Development is the default:

```sh
python3 scripts/evaluate_retrieval.py \
  --artifact /path/to/matching.db \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-dev-v2.json \
  --split dev --retriever keyword
```

Holdout labels are a separate explicitly protected input. Access requires both
the holdout split and the access flag; every authorized run records the UTC
timestamp and dataset digest in its report:

```sh
python3 scripts/evaluate_retrieval.py \
  --artifact /path/to/matching.db \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-holdout-v2.json \
  --split holdout --allow-holdout --retriever keyword
```

Do not tune on holdout results. Freeze the dataset, split, scorer, corpus and
provenance digests before any release-gate tuning. The later paired gate owns
comparison, bootstrap, resource limits and the Better Askman recommendation.
