# Askman release gate

Decision: **inconclusive**

## Inputs and builds

- Generated: `2026-09-27T11:45:08.920057+00:00`
- Evidence scope: `custom-dev-only-exploration`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --candidate-working-tree --main-data-dir /tmp/askman-goal.Fk5Zkh/main-import-home/Library/Application Support/askman --bundle /tmp/askman-goal.Fk5Zkh/bundle-description-v2 --dev-only --allow-custom-dev-dataset --custom-dev-manifest tests/fixtures/evaluation/dev-description-v3.manifest.json --dev-dataset tests/fixtures/evaluation/dev-description-v3.json --candidate-config tests/fixtures/evaluation/dev-description-v1-treatment-description.json --warmup-queries 5 --warm-queries 30 --output-json docs/reproducibility/artifacts/installed-main-vs-description-dev-v3-treatment.json --output-markdown docs/reproducibility/artifacts/installed-main-vs-description-dev-v3-treatment.md`
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
- Candidate bundle: `matching-bundle-v2:de6eda0ad301460e89606327a5af2d798317e05d7ff06498a7ec5e94b9b21574`
- Candidate bundle tree SHA-256: `223f5e9fab00e9eb79e807a0140cfd863735f674ef54e2fc53d1452eba071844`
- Main data tree SHA-256: `8dbd6badbb01e78b321608ebfb425b70eec1d7674d41991b3e4913c67b4033f8`
- Main database SHA-256: `ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db` (pinned evaluation baseline match: `True`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v4` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `df691502e66e851b3ad20d090c05085ddffe16072851731133f405ae2541ec7c`
- Holdout dataset SHA-256: `1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418`
- Candidate configuration: `description-dev-v1-treatment-description`; `description` text; `focused-v2` queries; top-8; `retain same-page candidates in the top-k; display the top three after reranking`; ranking `raw cosine distance minus 0.05 per shared query/candidate token`; distance `<= 0.6`; abstention `raw distance cutoff 0.60 plus scoped negation and unsupported-intent guards`; fusion `dense candidate pool reranked by 0.05 per shared lexical token`.
- Scorer SHA-256: `04127320c26df81b1f8be4dbbd9a26ed67d3aad34f2a327bcc0efdcdb2929f4f`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 11/30 | 9/30 |
| Success@3 | 15/30 | 14/30 |
| Coverage | 43/60 | 52/60 |
| Incorrect answered | 2/17 | 9/23 |
| False answers | 26/30 | 29/30 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 2/10 | 2/10 | 2/10 | 3/10 | 2/5 | 4/5 |
| linux | 7/10 | 5/10 | 10/10 | 8/10 | 5/5 | 5/5 |
| osx | 1/5 | 0/5 | 2/5 | 1/5 | 10/10 | 10/10 |
| windows | 1/5 | 2/5 | 1/5 | 2/5 | 9/10 | 10/10 |

## Scenario-family breakdown

| Family | main Success@1 | retrieval-v2 Success@1 | gain | main incorrect | retrieval-v2 incorrect |
| --- | ---: | ---: | ---: | ---: | ---: |
| descdev-v1-common-literal-punctuation-search | 1/5 | 1/5 | 0.0000 | 1/2 | 2/4 |
| descdev-v1-common-preserve-source-folders | 1/5 | 1/5 | 0.0000 | 0/1 | 0/1 |
| descdev-v1-common-quoted-csv-sort | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| descdev-v1-linux-compact-link-details | 4/5 | 3/5 | -0.2000 | 0/5 | 1/5 |
| descdev-v1-linux-current-service-run-logs | 3/5 | 2/5 | -0.2000 | 0/5 | 1/5 |
| descdev-v1-linux-per-process-memory-ranking | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| descdev-v1-osx-audio-transcription | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| descdev-v1-osx-reveal-file-in-finder | 1/5 | 0/5 | -0.2000 | 0/2 | 4/5 |
| descdev-v1-osx-screenshot-to-clipboard | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| descdev-v1-windows-literal-multiword-text-search | 1/5 | 2/5 | 0.2000 | 1/2 | 1/3 |
| descdev-v1-windows-recent-directory-filter | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| descdev-v1-windows-recursive-copy-with-empty-folders | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 95.645 ms | 87.208 ms | 238,027,496 B | 282,755,816 B |
| warmed query | 97.879 ms | 86.872 ms | 237,830,840 B | 238,682,832 B |

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
- `description-dev-v1-006` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `example-453abcea6ea8baded3debf3c7dc4ded44ee04405706cd1c95f4eb11faaab182c, example-218cad5dd34381708a69491c6060470eb2bf4d6ce10b57fd710a0122bedcca01, example-376799c4c44eb53e83e7abc95787b370bf11b82778628c98b5a369c61702957e`.
- `description-dev-v1-008` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `example-00bbff7f142bf20c7bcc5c53a7c669908fc51cbb59b00f400567fcd2a0055549`.
- `description-dev-v1-009` (descdev-v1-common-literal-punctuation-search/common), displayed IDs: `none`.
- `description-dev-v1-011` (descdev-v1-common-quoted-csv-sort/common), displayed IDs: `example-9401e615e42aac59e1c88665393b3e85c5bd4766b64dd13b1d3e1f8fb044d20c, example-5d09c75a518514e31f768a34add321aa8ffd2802819fce2b3c674266bbe18640, example-78126bf8914de541904d6bdad5a11e75e704ea53d4cd96c02196623b5dcbebfd`.
- `description-dev-v1-012` (descdev-v1-common-quoted-csv-sort/common), displayed IDs: `example-78126bf8914de541904d6bdad5a11e75e704ea53d4cd96c02196623b5dcbebfd, example-9401e615e42aac59e1c88665393b3e85c5bd4766b64dd13b1d3e1f8fb044d20c`.
- `description-dev-v1-013` (descdev-v1-common-quoted-csv-sort/common), displayed IDs: `example-9401e615e42aac59e1c88665393b3e85c5bd4766b64dd13b1d3e1f8fb044d20c`.

## Paired bootstrap

- Observed Success@1 gain: `-0.0667`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `-0.1667`.
- 95% interval: `-0.2000` to `0.0667`.

## Gate conditions

- overall Success@1 gain is below five percentage points
- fewer than two scenario families improved in Success@1
- Success@1 regressed in: descdev-v1-linux-compact-link-details, descdev-v1-linux-current-service-run-logs, descdev-v1-osx-reveal-file-in-finder
- overall Success@3 regressed
- overall incorrect_answered_tasks regressed
- overall false_answers_on_unanswerable regressed
- incorrect_answered_tasks regressed on platform common
- false_answers_on_unanswerable regressed on platform common
- success_at_3 regressed on platform linux
- incorrect_answered_tasks regressed on platform linux
- success_at_3 regressed on platform osx
- incorrect_answered_tasks regressed on platform osx
- false_answers_on_unanswerable regressed on platform windows
- paired bootstrap one-sided 95% lower bound is not above zero
- dev-only evidence cannot make a release decision

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
