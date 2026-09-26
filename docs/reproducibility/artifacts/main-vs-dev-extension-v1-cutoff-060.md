# Askman release gate

Decision: **inconclusive**

## Inputs and builds

- Generated: `2026-09-26T17:37:29.911910+00:00`
- Evidence scope: `custom-dev-only-exploration`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --candidate-working-tree --main-data-dir /tmp/askman-goal.Fk5Zkh/main-import-home/Library/Application Support/askman --bundle /tmp/askman-goal.Fk5Zkh/bundle-final-v2 --dev-only --allow-custom-dev-dataset --candidate-config tests/fixtures/evaluation/dev-extension-v1-candidate-same-page-cutoff-060.json --output-json /tmp/askman-dev-extension-v1-main-vs-cutoff-060.json --output-markdown /tmp/askman-dev-extension-v1-main-vs-cutoff-060.md`
- Freeze: `evaluation-v2-release-benchmark-v3`
- Main commit: `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
- Main Cargo.lock SHA-256: `79ee86b480ce00437f814657327b326b725ecd13965d1e958772b5d0ff415990`
- Main binary SHA-256: `e24f91a02008c7e9c6807d4d62c7d8b07170c61197f588e7ab3edf7513cfe38d`
- Candidate commit: `a1bac275508d14b14192da06f498ce288d85f6b6`
- Candidate Cargo.lock SHA-256: `c7eb0288a893ce1f387118cb0fc7370465d2efdfe33de1518ec2715b81c94f76`
- Candidate binary SHA-256: `5c3d7b1d3d8560ee42b61840ecac68da021f90e4f18fd536ca6cd007c6e558d7`
- Freeze manifest SHA-256: `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Independent holdout freeze: `None`
- Gate runner SHA-256: `d2f2e57bbd1a07225af53f81be2c0c94ccece80297cf1c991521dc5274fe4741`
- Candidate bundle: `matching-bundle-v2:8e53794515abdcaa0e304fb3ea533144461ae7018f87264c2fabcbd3fee191e4`
- Candidate bundle tree SHA-256: `082553b9446a6bf75aa0cdd2506ff283fbd1dc36ec40fc8333789fd17c74bfbf`
- Main data tree SHA-256: `8dbd6badbb01e78b321608ebfb425b70eec1d7674d41991b3e4913c67b4033f8`
- Main database SHA-256: `ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db` (pinned evaluation baseline match: `True`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v4` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `6c113bed013be3f532a8287c58a4f257347585c2be963d6c3b475d41ecc49905`
- Holdout dataset SHA-256: `1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418`
- Candidate configuration: `focused-same-page-cutoff-060-v1`; `main-compatible` text; `focused-v1` queries; top-8; `retain same-page candidates in the top-k; display the top three by raw cosine`; ranking `raw cosine distance, ascending`; distance `<= 0.6`; abstention `distance cutoff 0.60 plus scoped negation guards`; fusion `none`.
- Scorer SHA-256: `da2cc698922d48a225cb87f116bff933158f8be7180ebfe95bb47e6ef357c9ef`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 13/30 | 14/30 |
| Success@3 | 21/30 | 21/30 |
| Coverage | 24/60 | 24/60 |
| Incorrect answered | 3/24 | 3/24 |
| False answers | 0/30 | 0/30 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 2/10 | 3/10 | 7/10 | 7/10 | 0/5 | 0/5 |
| linux | 1/5 | 1/5 | 3/5 | 3/5 | 0/10 | 0/10 |
| osx | 8/10 | 8/10 | 9/10 | 9/10 | 0/5 | 0/5 |
| windows | 2/5 | 2/5 | 2/5 | 2/5 | 0/10 | 0/10 |

## Scenario-family breakdown

| Family | main Success@1 | retrieval-v2 Success@1 | gain | main incorrect | retrieval-v2 incorrect |
| --- | ---: | ---: | ---: | ---: | ---: |
| devx-common-find-by-extension | 0/5 | 1/5 | 0.2000 | 1/3 | 1/3 |
| devx-common-sort-ascending-lines | 2/5 | 2/5 | 0.0000 | 0/5 | 0/5 |
| devx-common-unsupported-create-user-account | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| devx-linux-df-human-readable | 1/5 | 1/5 | 0.0000 | 2/5 | 2/5 |
| devx-linux-unsupported-bluetooth-pairing | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| devx-linux-unsupported-keyboard-layout | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| devx-osx-save-screenshot | 4/5 | 4/5 | 0.0000 | 0/5 | 0/5 |
| devx-osx-synthesize-speech-to-file | 4/5 | 4/5 | 0.0000 | 0/4 | 0/4 |
| devx-osx-unsupported-set-display-resolution | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| devx-windows-move-across-drives | 2/5 | 2/5 | 0.0000 | 0/2 | 0/2 |
| devx-windows-unsupported-printer-setup | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| devx-windows-unsupported-set-system-time | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 86.812 ms | 85.819 ms | 237,732,536 B | 270,877,416 B |
| warmed query | 87.594 ms | 85.852 ms | 236,471,016 B | 236,667,576 B |

## Execution

- Main failed CLI runs: `0`.
- Candidate failed CLI runs: `0`.

## Failure examples

### main
- `devx-common-find-by-extension-02` (devx-common-find-by-extension/common), displayed IDs: `none`.
- `devx-common-find-by-extension-03` (devx-common-find-by-extension/common), displayed IDs: `none`.
- `devx-common-find-by-extension-05` (devx-common-find-by-extension/common), displayed IDs: `example-38141b4858477c7e64a25e8acd2a173e5a613b28bda28f5fb02c3c377c635d43`.
- `devx-linux-df-human-readable-02` (devx-linux-df-human-readable/linux), displayed IDs: `example-fde36aeb068ae85eb35667e80ad9fc1f2b8f79313764a2e6f16ef046e9409b40, example-9c3f58af214e9a579b9f6943bc021cdb16a28ef87eba18ff5d7bde38affe3e85, example-919b9bbb472e6c0d858c0468f2e80a835c266af944209da72656a19382fc61d5, example-e289813d18091e93b087eefe1f3b3a028a681047f0c372e67caea94d89bb2bd8`.
- `devx-linux-df-human-readable-04` (devx-linux-df-human-readable/linux), displayed IDs: `example-919b9bbb472e6c0d858c0468f2e80a835c266af944209da72656a19382fc61d5, example-fde36aeb068ae85eb35667e80ad9fc1f2b8f79313764a2e6f16ef046e9409b40, example-9c3f58af214e9a579b9f6943bc021cdb16a28ef87eba18ff5d7bde38affe3e85, example-e289813d18091e93b087eefe1f3b3a028a681047f0c372e67caea94d89bb2bd8, example-ca1e1eb99dc4ed5ed7666c3464df94fa1438a7f92ffcd52d8626f982c0f51f0b, example-18b8228973643cd6ddacd395575bcc764d5a30cf0eee12df9e0b74d406dbe5ef`.
- `devx-osx-synthesize-speech-to-file-01` (devx-osx-synthesize-speech-to-file/osx), displayed IDs: `none`.
- `devx-windows-move-across-drives-01` (devx-windows-move-across-drives/windows), displayed IDs: `none`.
- `devx-windows-move-across-drives-02` (devx-windows-move-across-drives/windows), displayed IDs: `none`.
- `devx-windows-move-across-drives-04` (devx-windows-move-across-drives/windows), displayed IDs: `none`.
### candidate
- `devx-common-find-by-extension-02` (devx-common-find-by-extension/common), displayed IDs: `none`.
- `devx-common-find-by-extension-03` (devx-common-find-by-extension/common), displayed IDs: `none`.
- `devx-common-find-by-extension-04` (devx-common-find-by-extension/common), displayed IDs: `example-00bbff7f142bf20c7bcc5c53a7c669908fc51cbb59b00f400567fcd2a0055549, example-376799c4c44eb53e83e7abc95787b370bf11b82778628c98b5a369c61702957e, example-453abcea6ea8baded3debf3c7dc4ded44ee04405706cd1c95f4eb11faaab182c`.
- `devx-linux-df-human-readable-02` (devx-linux-df-human-readable/linux), displayed IDs: `example-fde36aeb068ae85eb35667e80ad9fc1f2b8f79313764a2e6f16ef046e9409b40, example-9c3f58af214e9a579b9f6943bc021cdb16a28ef87eba18ff5d7bde38affe3e85, example-919b9bbb472e6c0d858c0468f2e80a835c266af944209da72656a19382fc61d5`.
- `devx-linux-df-human-readable-04` (devx-linux-df-human-readable/linux), displayed IDs: `example-919b9bbb472e6c0d858c0468f2e80a835c266af944209da72656a19382fc61d5, example-fde36aeb068ae85eb35667e80ad9fc1f2b8f79313764a2e6f16ef046e9409b40, example-9c3f58af214e9a579b9f6943bc021cdb16a28ef87eba18ff5d7bde38affe3e85`.
- `devx-osx-synthesize-speech-to-file-01` (devx-osx-synthesize-speech-to-file/osx), displayed IDs: `none`.
- `devx-windows-move-across-drives-01` (devx-windows-move-across-drives/windows), displayed IDs: `none`.
- `devx-windows-move-across-drives-02` (devx-windows-move-across-drives/windows), displayed IDs: `none`.
- `devx-windows-move-across-drives-04` (devx-windows-move-across-drives/windows), displayed IDs: `none`.

## Paired bootstrap

- Observed Success@1 gain: `0.0333`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `0.0000`.
- 95% interval: `0.0000` to `0.1000`.

## Gate conditions

- overall Success@1 gain is below five percentage points
- fewer than two scenario families improved in Success@1
- paired bootstrap one-sided 95% lower bound is not above zero
- dev-only evidence cannot make a release decision

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
