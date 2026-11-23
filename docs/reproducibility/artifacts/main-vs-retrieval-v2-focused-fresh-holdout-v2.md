# Askman release gate

Decision: **inconclusive**

## Inputs and builds

- Generated: `2026-09-26T21:09:48.085506+00:00`
- Evidence scope: `release-gate`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --main-ref main --candidate-ref ba74692cf79fa9c294f685fbade8f9315aeacdd1 --main-data-dir /tmp/askman-goal.Fk5Zkh/main-import-home/Library/Application Support/askman --bundle /tmp/askman-goal.Fk5Zkh/bundle-final-v2 --allow-holdout --independent-holdout-manifest tests/fixtures/evaluation/fresh-holdout-v2.manifest.json --output-json docs/reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v2.json --output-markdown docs/reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v2.md`
- Freeze: `evaluation-v2-release-benchmark-v3`
- Main commit: `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
- Main Cargo.lock SHA-256: `79ee86b480ce00437f814657327b326b725ecd13965d1e958772b5d0ff415990`
- Main binary SHA-256: `e24f91a02008c7e9c6807d4d62c7d8b07170c61197f588e7ab3edf7513cfe38d`
- Candidate commit: `ba74692cf79fa9c294f685fbade8f9315aeacdd1`
- Candidate Cargo.lock SHA-256: `c7eb0288a893ce1f387118cb0fc7370465d2efdfe33de1518ec2715b81c94f76`
- Candidate binary SHA-256: `20193571cef751a3d38fd1e12f9d26dd3512fbcc04498d78f128eee906ec3e8f`
- Freeze manifest SHA-256: `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Independent holdout freeze: `fresh-holdout-v2-freeze-2026-09-26`
- Gate runner SHA-256: `201b272c4752bdb713565e600793a8eebdbe9d9888e6a22fe4f57a187edae49a`
- Candidate bundle: `matching-bundle-v2:8e53794515abdcaa0e304fb3ea533144461ae7018f87264c2fabcbd3fee191e4`
- Candidate bundle tree SHA-256: `082553b9446a6bf75aa0cdd2506ff283fbd1dc36ec40fc8333789fd17c74bfbf`
- Main data tree SHA-256: `8dbd6badbb01e78b321608ebfb425b70eec1d7674d41991b3e4913c67b4033f8`
- Main database SHA-256: `ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db` (pinned evaluation baseline match: `True`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v3` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `216c0e26f24fda7df197011be4f8add33b6852b7907b32966b0c77e0a26c947d`
- Holdout dataset SHA-256: `8019c67c7ff13f6a9d06159ea0cf12cc3914011c69686fa2b5c93270f879797d`
- Candidate configuration: `focused-same-page-cutoff-060-lexical-005-v1`; `main-compatible` text; `focused-v1` queries; top-8; `retain same-page candidates in the top-k; display the top three after reranking`; ranking `raw cosine distance minus 0.05 per shared query/candidate token`; distance `<= 0.6`; abstention `raw distance cutoff 0.60 plus scoped negation guards`; fusion `dense candidate pool reranked by 0.05 per shared lexical token`.
- Scorer SHA-256: `da2cc698922d48a225cb87f116bff933158f8be7180ebfe95bb47e6ef357c9ef`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 30/60 | 43/60 |
| Success@3 | 36/60 | 47/60 |
| Coverage | 58/120 | 56/120 |
| Incorrect answered | 16/52 | 3/50 |
| False answers | 6/60 | 6/60 |

## Split-specific quality

| Split | Metric | main | retrieval-v2 |
| --- | --- | ---: | ---: |
| dev | Success@1 | 18/30 | 28/30 |
| dev | Success@3 | 23/30 | 30/30 |
| dev | False answers | 1/30 | 1/30 |
| holdout | Success@1 | 12/30 | 15/30 |
| holdout | Success@3 | 13/30 | 17/30 |
| holdout | False answers | 5/30 | 5/30 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 12/17 | 12/17 | 14/17 | 13/17 | 2/13 | 2/13 |
| linux | 11/16 | 14/16 | 14/16 | 14/16 | 3/14 | 3/14 |
| osx | 5/14 | 9/14 | 5/14 | 12/14 | 0/16 | 0/16 |
| windows | 2/13 | 8/13 | 3/13 | 8/13 | 1/17 | 1/17 |

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
| fresh2-family-001 | 0/1 | 0/1 | 0.0000 | 1/1 | 0/0 |
| fresh2-family-002 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-003 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-004 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-005 | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-006 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-007 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-008 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-010 | 0/1 | 1/1 | 1.0000 | 0/1 | 0/1 |
| fresh2-family-011 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-012 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-013 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-016 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-018 | 1/1 | 0/1 | -1.0000 | 0/1 | 0/0 |
| fresh2-family-019 | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-021 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-022 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-023 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-024 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-025 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-026 | 0/1 | 0/1 | 0.0000 | 1/1 | 1/1 |
| fresh2-family-027 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-028 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-029 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-030 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-031 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-033 | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-034 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-035 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-039 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-041 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-042 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-043 | 0/1 | 1/1 | 1.0000 | 1/1 | 0/1 |
| fresh2-family-044 | 0/1 | 0/1 | 0.0000 | 1/1 | 0/1 |
| fresh2-family-045 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-046 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-047 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-048 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-049 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-050 | 0/1 | 0/1 | 0.0000 | 1/1 | 0/1 |
| fresh2-family-051 | 0/1 | 0/1 | 0.0000 | 1/1 | 1/1 |
| fresh2-family-052 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-053 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-058 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-059 | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-061 | 0/1 | 1/1 | 1.0000 | 1/1 | 0/1 |
| fresh2-family-062 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-063 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-064 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-065 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-066 | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-067 | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-068 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-069 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-070 | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh2-family-071 | 0/1 | 1/1 | 1.0000 | 1/1 | 0/1 |
| fresh2-family-072 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-074 | 0/1 | 0/1 | 0.0000 | 1/1 | 1/1 |
| fresh2-family-075 | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh2-family-079 | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 86.773 ms | 86.212 ms | 236,421,816 B | 282,886,888 B |
| holdout fresh | 92.330 ms | 85.911 ms | 237,404,856 B | 237,290,192 B |
| warmed query | 86.804 ms | 85.891 ms | 236,077,776 B | 236,094,136 B |

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
- `fresh2-common-01` (fresh2-family-001/common), displayed IDs: `example-453abcea6ea8baded3debf3c7dc4ded44ee04405706cd1c95f4eb11faaab182c`.
- `fresh2-common-03` (fresh2-family-003/common), displayed IDs: `example-899be5423d13c42fe2a430cc06b8539e18124b979b0555ed71bd134c2f875375, example-8ce4049b12e6fbdd8ddf55f64fe04680b35071710b29124b53a08b088e26429d, example-c5fcd87e47e9d553fdb1891154e8176aabb962d6465da156970ef98684e31805`.
### candidate
- `dev-v2r1-devwindows-unsupported-a-04` (dev39-windows-unsupported-registry/windows), displayed IDs: `example-34ec551605a714d9a5aabb76d979f066b344c34efb17a6f53748b87870ee4078`.
- `fresh2-common-01` (fresh2-family-001/common), displayed IDs: `none`.
- `fresh2-common-03` (fresh2-family-003/common), displayed IDs: `example-899be5423d13c42fe2a430cc06b8539e18124b979b0555ed71bd134c2f875375, example-8ce4049b12e6fbdd8ddf55f64fe04680b35071710b29124b53a08b088e26429d, example-c5fcd87e47e9d553fdb1891154e8176aabb962d6465da156970ef98684e31805`.
- `fresh2-common-05` (fresh2-family-005/common), displayed IDs: `none`.
- `fresh2-common-13` (fresh2-family-013/common), displayed IDs: `example-899be5423d13c42fe2a430cc06b8539e18124b979b0555ed71bd134c2f875375`.
- `fresh2-common-18` (fresh2-family-018/common), displayed IDs: `none`.
- `fresh2-common-19` (fresh2-family-019/common), displayed IDs: `none`.
- `fresh2-linux-06` (fresh2-family-026/linux), displayed IDs: `example-e1d50ec8bcbdbb1cde2d2d97c841c00ee709fc61c9e125b61d5e6e1cea601d16`.
- `fresh2-linux-07` (fresh2-family-027/linux), displayed IDs: `example-5270e7367ac85aacdf86577d153a225237069a6d0d8a97e0eb86ee127154898b`.
- `fresh2-linux-09` (fresh2-family-029/linux), displayed IDs: `example-ca1e1eb99dc4ed5ed7666c3464df94fa1438a7f92ffcd52d8626f982c0f51f0b, example-fde36aeb068ae85eb35667e80ad9fc1f2b8f79313764a2e6f16ef046e9409b40, example-919b9bbb472e6c0d858c0468f2e80a835c266af944209da72656a19382fc61d5`.

## Paired bootstrap

- Observed Success@1 gain: `0.2167`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `0.1167`.
- 95% interval: `0.1000` to `0.3333`.

## Independent holdout check

- Holdout Success@1 gain: `0.1000`.
- One-sided 95% lower bound: `0.0000`.
- Independent holdout decision: **inconclusive**.

## Gate conditions

- Success@1 regressed in: fresh2-family-018
- success_at_3 regressed on platform common
- independent holdout success_at_3 regressed on platform common
- independent holdout paired bootstrap one-sided 95% lower bound is not above zero

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
