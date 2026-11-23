# Description embedding A/B — dev v3

**Decision: reject description-only embeddings. Keep installed main shipped.**
This was a development-only comparison, not independent validation.

## Setup

One factor changed: `main-compatible` embedding text versus the example's
description only. Both arms used the same 60-task frozen cohort, 142 parser-v4
records, MiniLM revision, focused-v2 query rules, top-8 dense pool, same-page
selection, 0.60 raw-distance cutoff, 0.05 lexical rerank, guards, and display
limit. Bundle visible-record digests matched. Both reports used the installed
main CLI/data snapshot as their reference and built the same candidate binary.

Dataset SHA-256:
`df691502e66e851b3ad20d090c05085ddffe16072851731133f405ae2541ec7c`.
Freeze manifest SHA-256:
`d57c7aaf8dfad686c73e551090b0346b97ca2949d7eedae2ca683e95f10d1cb4`.
The task labels were audited against source pages and exact example IDs before
retrieval. The v1 and v2 preflight freezes are preserved; neither executed
queries. V3 passed pinned freeze, schema, corpus, and label validation.

## Results

Success@1 and Success@3 use the 30 answerable tasks. False answers use the 30
unanswerable tasks. Incorrect answered is reported as incorrect/answered
answerable tasks.

| Candidate | Success@1 (main → candidate) | Success@3 | False answers | Incorrect answered |
| --- | ---: | ---: | ---: | ---: |
| Main-compatible control | 11/30 → 11/30 | 15/30 → 14/30 | 26/30 → 23/30 | 2/17 → 1/15 |
| Description-only treatment | 11/30 → 9/30 | 15/30 → 14/30 | 26/30 → 29/30 | 2/17 → 9/23 |

Directly comparing the two candidates on the same cohort, description-only lost
2 first results, tied top-three results at 14/30, added 6 false answers
(23/30→29/30), and raised incorrect answers from 1/15 to 9/23. These are
descriptive same-cohort aggregates; the runner retains only ten failure
examples per arm, so a candidate-vs-candidate paired interval cannot be
reconstructed. Each main-vs-candidate paired bootstrap lower bound was below
zero. Both canonical runs correctly returned `inconclusive` in dev-only mode.

Platform Success@1/Success@3:

| Platform | Installed main | Control | Description-only |
| --- | ---: | ---: | ---: |
| Common | 2/10, 2/10 | 2/10, 2/10 | 2/10, 3/10 |
| Linux | 7/10, 10/10 | 6/10, 9/10 | 5/10, 8/10 |
| macOS | 1/5, 2/5 | 2/5, 2/5 | 0/5, 1/5 |
| Windows | 1/5, 1/5 | 1/5, 1/5 | 2/5, 2/5 |

The treatment improved Windows and common top-three counts, but regressed
Linux and macOS, and sharply worsened answer safety. It fails the fixed
quality guardrails.

## Operations

Both arms ran with network-denied query processes and zero CLI execution
failures. All measured latency and memory phases stayed within the 20% gate
ceiling. Description-only fresh-process p95 was 87.208 ms versus main's
95.645 ms; peak memory was 282,755,816 B versus 238,027,496 B (+18.8%). Warmed
p95 was 86.872 ms versus 97.879 ms; peak memory was 238,682,832 B versus
237,830,840 B. The fresh-process memory result is near the ceiling and does
not compensate for the quality regressions.

The treatment is rejected without tuning. No holdout dataset, labels, reports,
or results were read or scored; the dev-only gate read only the benchmark
freeze manifest metadata. The earlier authorized v3 holdout belongs to the
focused query-rule candidate and does not validate this representation. Any
new independent score needs a new unseen holdout and explicit authorization.

## Artifacts

- [Machine-readable comparison](description-embedding-dev-v3-comparison.json)
- [Control gate report](installed-main-vs-description-dev-v3-control.md)
- [Treatment gate report](installed-main-vs-description-dev-v3-treatment.md)
- [Frozen protocol](description-embedding-dev-v3-protocol.md)
- [Pinned dev dataset](../../../tests/fixtures/evaluation/dev-description-v3.json)
- [Pinned freeze manifest](../../../tests/fixtures/evaluation/dev-description-v3.manifest.json)
