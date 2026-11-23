# Askman release gate

Decision: **inconclusive**

## Inputs and builds

- Generated: `2026-09-27T11:43:06.130823+00:00`
- Evidence scope: `custom-dev-only-exploration`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --candidate-working-tree --main-data-dir /tmp/askman-goal.Fk5Zkh/main-import-home/Library/Application Support/askman --bundle /tmp/askman-goal.Fk5Zkh/bundle-final-v2 --dev-only --allow-custom-dev-dataset --custom-dev-manifest tests/fixtures/evaluation/dev-description-v3.manifest.json --dev-dataset tests/fixtures/evaluation/dev-description-v3.json --candidate-config tests/fixtures/evaluation/dev-description-v1-control-main-compatible.json --warmup-queries 5 --warm-queries 30 --output-json docs/reproducibility/artifacts/installed-main-vs-description-dev-v3-control.json --output-markdown docs/reproducibility/artifacts/installed-main-vs-description-dev-v3-control.md`
- Freeze: `evaluation-v2-release-benchmark-v3`
- Main commit: `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
- Main Cargo.lock SHA-256: `79ee86b480ce00437f814657327b326b725ecd13965d1e958772b5d0ff415990`
- Main binary SHA-256: `e24f91a02008c7e9c6807d4d62c7d8b07170c61197f588e7ab3edf7513cfe38d`
- Candidate commit: `03e60bc72d191154d7d3f6c13a3e8afb06f4b1ee`
- Candidate Cargo.lock SHA-256: `c7eb0288a893ce1f387118cb0fc7370465d2efdfe33de1518ec2715b81c94f76`
- Candidate binary SHA-256: `c7bfb4093eccee8f9c32f2e324d0d5d525978ee0d0dfc01ba668213d91ad2e12`
- Freeze manifest SHA-256: `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Independent holdout freeze: `None`
- Gate runner SHA-256: `8b4df2843eb71a9c066fab2a5e12450096e81d83b865e473e5bae30addbd4e38`
- Candidate bundle: `matching-bundle-v2:8e53794515abdcaa0e304fb3ea533144461ae7018f87264c2fabcbd3fee191e4`
- Candidate bundle tree SHA-256: `082553b9446a6bf75aa0cdd2506ff283fbd1dc36ec40fc8333789fd17c74bfbf`
- Main data tree SHA-256: `8dbd6badbb01e78b321608ebfb425b70eec1d7674d41991b3e4913c67b4033f8`
- Main database SHA-256: `ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db` (pinned evaluation baseline match: `True`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v4` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `df691502e66e851b3ad20d090c05085ddffe16072851731133f405ae2541ec7c`
- Holdout dataset SHA-256: `1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418`
- Candidate configuration: `description-dev-v1-control-main-compatible`; `main-compatible` text; `focused-v2` queries; top-8; `retain same-page candidates in the top-k; display the top three after reranking`; ranking `raw cosine distance minus 0.05 per shared query/candidate token`; distance `<= 0.6`; abstention `raw distance cutoff 0.60 plus scoped negation and unsupported-intent guards`; fusion `dense candidate pool reranked by 0.05 per shared lexical token`.
- Scorer SHA-256: `04127320c26df81b1f8be4dbbd9a26ed67d3aad34f2a327bcc0efdcdb2929f4f`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 11/30 | 11/30 |
| Success@3 | 15/30 | 14/30 |
| Coverage | 43/60 | 38/60 |
| Incorrect answered | 2/17 | 1/15 |
| False answers | 26/30 | 23/30 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 2/10 | 2/10 | 2/10 | 2/10 | 2/5 | 1/5 |
| linux | 7/10 | 6/10 | 10/10 | 9/10 | 5/5 | 4/5 |
| osx | 1/5 | 2/5 | 2/5 | 2/5 | 10/10 | 10/10 |
| windows | 1/5 | 1/5 | 1/5 | 1/5 | 9/10 | 8/10 |

## Scenario-family breakdown

| Family | main Success@1 | retrieval-v2 Success@1 | gain | main incorrect | retrieval-v2 incorrect |
| --- | ---: | ---: | ---: | ---: | ---: |
| descdev-v1-common-literal-punctuation-search | 1/5 | 1/5 | 0.0000 | 1/2 | 0/1 |
| descdev-v1-common-preserve-source-folders | 1/5 | 1/5 | 0.0000 | 0/1 | 0/1 |
| descdev-v1-common-quoted-csv-sort | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| descdev-v1-linux-compact-link-details | 4/5 | 3/5 | -0.2000 | 0/5 | 0/5 |
| descdev-v1-linux-current-service-run-logs | 3/5 | 3/5 | 0.0000 | 0/5 | 1/5 |
| descdev-v1-linux-per-process-memory-ranking | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| descdev-v1-osx-audio-transcription | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| descdev-v1-osx-reveal-file-in-finder | 1/5 | 2/5 | 0.2000 | 0/2 | 0/2 |
| descdev-v1-osx-screenshot-to-clipboard | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| descdev-v1-windows-literal-multiword-text-search | 1/5 | 1/5 | 0.0000 | 1/2 | 0/1 |
| descdev-v1-windows-recent-directory-filter | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| descdev-v1-windows-recursive-copy-with-empty-folders | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 94.157 ms | 97.410 ms | 237,912,760 B | 271,893,200 B |
| warmed query | 98.236 ms | 102.634 ms | 236,798,648 B | 238,371,536 B |

## Execution

- Main failed CLI runs: `0`.
- Candidate failed CLI runs: `0`.

## Failure examples

### main
- `description-dev-v1-001` (descdev-v1-common-preserve-source-folders/common), displayed IDs: `none`.
- `description-dev-v1-002` (descdev-v1-common-preserve-source-folders/common), displayed IDs: `none`.
- `description-dev-v1-003` (descdev-v1-common-preserve-source-folders/common), displayed IDs: `none`.
- `description-dev-v1-004` (descdev-v1-common-preserve-source-folders/common), displayed IDs: `none`.
- `description-dev-v1-006` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `example-453abcea6ea8baded3debf3c7dc4ded44ee04405706cd1c95f4eb11faaab182c`.
- `description-dev-v1-007` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `none`.
- `description-dev-v1-008` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `none`.
- `description-dev-v1-009` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `none`.
- `description-dev-v1-011` (descdev-v1-common-quoted-csv-sort/common), displayed IDs: `example-78126bf8914de541904d6bdad5a11e75e704ea53d4cd96c02196623b5dcbebfd`.
- `description-dev-v1-014` (descdev-v1-common-quoted-csv-sort/common), displayed IDs: `example-78126bf8914de541904d6bdad5a11e75e704ea53d4cd96c02196623b5dcbebfd, example-9401e615e42aac59e1c88665393b3e85c5bd4766b64dd13b1d3e1f8fb044d20c, example-5d09c75a518514e31f768a34add321aa8ffd2802819fce2b3c674266bbe18640`.
### candidate
- `description-dev-v1-001` (descdev-v1-common-preserve-source-folders/common), displayed IDs: `none`.
- `description-dev-v1-002` (descdev-v1-common-preserve-source-folders/common), displayed IDs: `none`.
- `description-dev-v1-003` (descdev-v1-common-preserve-source-folders/common), displayed IDs: `none`.
- `description-dev-v1-004` (descdev-v1-common-preserve-source-folders/common), displayed IDs: `none`.
- `description-dev-v1-006` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `none`.
- `description-dev-v1-007` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `none`.
- `description-dev-v1-008` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `none`.
- `description-dev-v1-009` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `none`.
- `description-dev-v1-014` (descdev-v1-common-quoted-csv-sort/common), displayed IDs: `example-9401e615e42aac59e1c88665393b3e85c5bd4766b64dd13b1d3e1f8fb044d20c, example-78126bf8914de541904d6bdad5a11e75e704ea53d4cd96c02196623b5dcbebfd, example-5d09c75a518514e31f768a34add321aa8ffd2802819fce2b3c674266bbe18640`.
- `description-dev-v1-019` (descdev-v1-linux-current-service-run-logs/linux), displayed IDs: `example-635808eeb22bdbe61688c222a223c384429fa1d9dd798154c7937d5d3ad28ade`.

## Paired bootstrap

- Observed Success@1 gain: `0.0000`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `-0.0667`.
- 95% interval: `-0.1000` to `0.1000`.

## Gate conditions

- overall Success@1 gain is below five percentage points
- fewer than two scenario families improved in Success@1
- Success@1 regressed in: descdev-v1-linux-compact-link-details
- overall Success@3 regressed
- success_at_3 regressed on platform linux
- incorrect_answered_tasks regressed on platform linux
- paired bootstrap one-sided 95% lower bound is not above zero
- dev-only evidence cannot make a release decision

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
