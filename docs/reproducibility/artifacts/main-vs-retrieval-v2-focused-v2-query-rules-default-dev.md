# Askman release gate

Decision: **inconclusive**

## Inputs and builds

- Generated: `2026-09-26T22:43:11.820227+00:00`
- Evidence scope: `dev-only-verification`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --candidate-working-tree --main-data-dir /tmp/askman-goal.Fk5Zkh/main-import-home/Library/Application Support/askman --bundle /tmp/askman-goal.Fk5Zkh/bundle-final-v2 --dev-only --warmup-queries 5 --warm-queries 30 --output-json docs/reproducibility/artifacts/main-vs-retrieval-v2-focused-v2-query-rules-default-dev.json --output-markdown docs/reproducibility/artifacts/main-vs-retrieval-v2-focused-v2-query-rules-default-dev.md`
- Freeze: `evaluation-v2-release-benchmark-v3`
- Main commit: `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
- Main Cargo.lock SHA-256: `79ee86b480ce00437f814657327b326b725ecd13965d1e958772b5d0ff415990`
- Main binary SHA-256: `e24f91a02008c7e9c6807d4d62c7d8b07170c61197f588e7ab3edf7513cfe38d`
- Candidate commit: `03e60bc72d191154d7d3f6c13a3e8afb06f4b1ee`
- Candidate Cargo.lock SHA-256: `c7eb0288a893ce1f387118cb0fc7370465d2efdfe33de1518ec2715b81c94f76`
- Candidate binary SHA-256: `e727941c9efbfadc0ba4bd89885d880d8f3b6ca27d663f88c502e89c4d91e1b5`
- Freeze manifest SHA-256: `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Independent holdout freeze: `None`
- Gate runner SHA-256: `f193530c0b140cba175e2a0d8e067d8e843519a9ae2c5a5c5e8eb69d2c71857a`
- Candidate bundle: `matching-bundle-v2:8e53794515abdcaa0e304fb3ea533144461ae7018f87264c2fabcbd3fee191e4`
- Candidate bundle tree SHA-256: `082553b9446a6bf75aa0cdd2506ff283fbd1dc36ec40fc8333789fd17c74bfbf`
- Main data tree SHA-256: `8dbd6badbb01e78b321608ebfb425b70eec1d7674d41991b3e4913c67b4033f8`
- Main database SHA-256: `ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db` (pinned evaluation baseline match: `True`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v3` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `216c0e26f24fda7df197011be4f8add33b6852b7907b32966b0c77e0a26c947d`
- Holdout dataset SHA-256: `1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418`
- Candidate configuration: `focused-v2-same-page-cutoff-060-lexical-005-v1`; `main-compatible` text; `focused-v2` queries; top-8; `retain same-page candidates in the top-k; display the top three after reranking`; ranking `raw cosine distance minus 0.05 per shared query/candidate token`; distance `<= 0.6`; abstention `raw distance cutoff 0.60 plus scoped negation and unsupported-intent guards`; fusion `dense candidate pool reranked by 0.05 per shared lexical token`.
- Scorer SHA-256: `04127320c26df81b1f8be4dbbd9a26ed67d3aad34f2a327bcc0efdcdb2929f4f`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 18/30 | 28/30 |
| Success@3 | 23/30 | 30/30 |
| Coverage | 31/60 | 31/60 |
| Incorrect answered | 7/30 | 0/30 |
| False answers | 1/30 | 1/30 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 9/10 | 9/10 | 10/10 | 10/10 | 0/5 | 0/5 |
| linux | 7/10 | 10/10 | 10/10 | 10/10 | 0/5 | 0/5 |
| osx | 1/5 | 4/5 | 1/5 | 5/5 | 0/10 | 0/10 |
| windows | 1/5 | 5/5 | 2/5 | 5/5 | 1/10 | 1/10 |

## Scenario-family breakdown

| Family | main Success@1 | retrieval-v2 Success@1 | gain | main incorrect | retrieval-v2 incorrect |
| --- | ---: | ---: | ---: | ---: | ---: |
| dev39-common-file-content | 4/5 | 4/5 | 0.0000 | 0/5 | 0/5 |
| dev39-common-file-copy | 5/5 | 5/5 | 0.0000 | 0/5 | 0/5 |
| dev39-common-unsupported-file-encryption | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-linux-firewall-unsupported | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-linux-interface-address | 3/5 | 5/5 | 0.4000 | 0/5 | 0/5 |
| dev39-linux-systemd-restart | 4/5 | 5/5 | 0.2000 | 0/5 | 0/5 |
| dev39-osx-clipboard-output | 1/5 | 4/5 | 0.6000 | 4/5 | 0/5 |
| dev39-osx-unsupported-dns | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-osx-unsupported-exif | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-windows-file-copy-single | 1/5 | 5/5 | 0.8000 | 3/5 | 0/5 |
| dev39-windows-unsupported-event-log | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-windows-unsupported-registry | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 86.747 ms | 86.645 ms | 236,339,920 B | 283,067,136 B |
| warmed query | 86.950 ms | 90.365 ms | 236,470,968 B | 237,732,536 B |

## Execution

- Main failed CLI runs: `0`.
- Candidate failed CLI runs: `0`.

## Failure examples

### main
- `dev-v2r1-devosx-clipboard-01` (dev39-osx-clipboard-output/osx), displayed IDs: `example-c7e7560a61cc444906eb6f2eb172fd18d2dda57f6d72cc794370fb3889a77238`.
- `dev-v2r1-devosx-clipboard-02` (dev39-osx-clipboard-output/osx), displayed IDs: `example-c7e7560a61cc444906eb6f2eb172fd18d2dda57f6d72cc794370fb3889a77238`.
- `dev-v2r1-devosx-clipboard-04` (dev39-osx-clipboard-output/osx), displayed IDs: `example-c7e7560a61cc444906eb6f2eb172fd18d2dda57f6d72cc794370fb3889a77238, example-72a428d0a15e820cacc86ef2c9453ad0ce9c0a99020cd0c0c2c6a9db91d28e39`.
- `dev-v2r1-devosx-clipboard-05` (dev39-osx-clipboard-output/osx), displayed IDs: `example-c7e7560a61cc444906eb6f2eb172fd18d2dda57f6d72cc794370fb3889a77238`.
- `dev-v2r1-devwindows-file-copy-01` (dev39-windows-file-copy-single/windows), displayed IDs: `example-bf08095597f0c34db32a46737a7e9ffa58bd8150b4d2ef20940f750a30603e2b`.
- `dev-v2r1-devwindows-file-copy-03` (dev39-windows-file-copy-single/windows), displayed IDs: `example-bf08095597f0c34db32a46737a7e9ffa58bd8150b4d2ef20940f750a30603e2b`.
- `dev-v2r1-devwindows-file-copy-04` (dev39-windows-file-copy-single/windows), displayed IDs: `example-bf08095597f0c34db32a46737a7e9ffa58bd8150b4d2ef20940f750a30603e2b`.
- `dev-v2r1-devwindows-unsupported-a-04` (dev39-windows-unsupported-registry/windows), displayed IDs: `example-34ec551605a714d9a5aabb76d979f066b344c34efb17a6f53748b87870ee4078`.
### candidate
- `dev-v2r1-devwindows-unsupported-a-04` (dev39-windows-unsupported-registry/windows), displayed IDs: `example-34ec551605a714d9a5aabb76d979f066b344c34efb17a6f53748b87870ee4078`.

## Paired bootstrap

- Observed Success@1 gain: `0.3333`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `0.2000`.
- 95% interval: `0.1667` to `0.5000`.

## Gate conditions

- dev-only evidence cannot make a release decision

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
