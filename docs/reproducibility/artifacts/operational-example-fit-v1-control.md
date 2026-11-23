# Askman release gate

Decision: **inconclusive**

## Inputs and builds

- Generated: `2026-09-27T12:58:12.193863+00:00`
- Evidence scope: `custom-dev-only-exploration`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --main-ref main --candidate-working-tree --dev-only --allow-custom-dev-dataset --custom-dev-manifest docs/reproducibility/artifacts/operational-compatibility-dev-v2-freeze.json --dev-dataset tests/fixtures/evaluation/operational-compatibility-dev-v2.json --main-data-dir /tmp/askman-operational-fit-main-data --bundle /tmp/askman-operational-fit-v1-bundle --candidate-config docs/reproducibility/artifacts/operational-example-fit-v1-control-config.json --output-json docs/reproducibility/artifacts/operational-example-fit-v1-control.json --output-markdown docs/reproducibility/artifacts/operational-example-fit-v1-control.md`
- Freeze: `evaluation-v2-release-benchmark-v3`
- Main commit: `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
- Main Cargo.lock SHA-256: `79ee86b480ce00437f814657327b326b725ecd13965d1e958772b5d0ff415990`
- Main binary SHA-256: `e24f91a02008c7e9c6807d4d62c7d8b07170c61197f588e7ab3edf7513cfe38d`
- Candidate commit: `03e60bc72d191154d7d3f6c13a3e8afb06f4b1ee`
- Candidate Cargo.lock SHA-256: `c7eb0288a893ce1f387118cb0fc7370465d2efdfe33de1518ec2715b81c94f76`
- Candidate binary SHA-256: `bb00de24b2605a5c1268d7c9fd01ebec853461132e07a0c318dfa64614d9680e`
- Freeze manifest SHA-256: `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Independent holdout freeze: `None`
- Gate runner SHA-256: `ffa91fc2d60b4441c63d9333bdc488f6e25db40e66312817f0a6b55e5be1c5c2`
- Candidate bundle: `matching-bundle-v2:38242507ec57eb92a64f9fd96831d49ccc318378f4e644b06c3e302f7b8c0157`
- Candidate bundle tree SHA-256: `54d9abcf54147c1dc199099968e3e7315d3f65a43006925768612328862d7fa6`
- Main data tree SHA-256: `9f29939323a64ca28328388f166451476df7af30113d30a67f7ebf8691467149`
- Main database SHA-256: `d8b83e0e6fc9329d65bf3c5ef42c946babbdc2bdb1897b266ed654814c00d095` (pinned evaluation baseline match: `False`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v4` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `ab34155b640eb1227df53cc8e7ad3e5c034b71b2aa65f85670fa4f9b99b0c964`
- Holdout dataset SHA-256: `1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418`
- Candidate configuration: `operational-example-fit-v1-control`; `main-compatible` text; `focused-v2` queries; top-8; `retain same-page candidates in the top-k; display the top three after reranking`; ranking `raw cosine distance minus 0.05 per shared query/candidate token`; distance `<= 0.6`; abstention `raw distance cutoff 0.60 plus scoped negation and unsupported-intent guards`; fusion `dense candidate pool reranked by 0.05 per shared lexical token`.
- Scorer SHA-256: `f1da9807343832411db3d70d6b747a62911c36e6627f9f731982ed8742bc2874`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 19/28 | 23/28 |
| Success@3 | 21/28 | 25/28 |
| Coverage | 50/60 | 49/60 |
| Incorrect answered | 5/26 | 1/26 |
| False answers | 24/32 | 23/32 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 6/7 | 6/7 | 7/7 | 7/7 | 5/8 | 5/8 |
| linux | 5/7 | 6/7 | 6/7 | 7/7 | 8/8 | 7/8 |
| osx | 4/8 | 5/8 | 4/8 | 5/8 | 5/7 | 5/7 |
| windows | 4/6 | 6/6 | 4/6 | 6/6 | 6/9 | 6/9 |

## Scenario-family breakdown

| Family | main Success@1 | retrieval-v2 Success@1 | gain | main incorrect | retrieval-v2 incorrect |
| --- | ---: | ---: | ---: | ---: | ---: |
| opcompat-v1-F01 | 2/3 | 3/3 | 0.3333 | 1/3 | 0/3 |
| opcompat-v1-F02 | 0/3 | 1/3 | 0.3333 | 1/2 | 0/2 |
| opcompat-v1-F03 | 1/2 | 1/2 | 0.0000 | 0/1 | 0/1 |
| opcompat-v1-F04 | 3/3 | 3/3 | 0.0000 | 0/3 | 0/3 |
| opcompat-v1-F05 | 1/2 | 1/2 | 0.0000 | 0/2 | 0/2 |
| opcompat-v1-F06 | 2/2 | 2/2 | 0.0000 | 0/2 | 0/2 |
| opcompat-v1-F07 | 2/2 | 2/2 | 0.0000 | 0/2 | 0/2 |
| opcompat-v1-F08 | 2/2 | 2/2 | 0.0000 | 0/2 | 0/2 |
| opcompat-v1-F09 | 2/3 | 3/3 | 0.3333 | 1/3 | 0/3 |
| opcompat-v1-F10 | 2/2 | 2/2 | 0.0000 | 0/2 | 0/2 |
| opcompat-v1-F11 | 2/3 | 2/3 | 0.0000 | 1/3 | 1/3 |
| opcompat-v1-F12 | 0/1 | 1/1 | 1.0000 | 1/1 | 0/1 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 95.244 ms | 88.142 ms | 238,174,904 B | 271,074,000 B |
| warmed query | 87.396 ms | 87.004 ms | 236,143,288 B | 236,274,384 B |

## Execution

- Main failed CLI runs: `0`.
- Candidate failed CLI runs: `0`.

## Failure examples

### main
- `opcompat-v1-003` (opcompat-v1-F01/osx), displayed IDs: `example-2e1ea6fc34202b3bef21fe52bfd7839f721d66f274dc0690210f2e4503a95351`.
- `opcompat-v1-004` (opcompat-v1-F01/windows), displayed IDs: `example-38141b4858477c7e64a25e8acd2a173e5a613b28bda28f5fb02c3c377c635d43`.
- `opcompat-v1-005` (opcompat-v1-F01/common), displayed IDs: `example-899be5423d13c42fe2a430cc06b8539e18124b979b0555ed71bd134c2f875375, example-8ce4049b12e6fbdd8ddf55f64fe04680b35071710b29124b53a08b088e26429d`.
- `opcompat-v1-007` (opcompat-v1-F02/osx), displayed IDs: `none`.
- `opcompat-v1-008` (opcompat-v1-F02/windows), displayed IDs: `example-8158f89e24f5fe56d7e7c4f5d98a3c2c2bd3fc5d4495e5233d81e9652993c0b3`.
- `opcompat-v1-010` (opcompat-v1-F02/linux), displayed IDs: `example-1701ba64bdde6b5279e26c70c9d8a21f4f44ae584c2ec202143006693cf82b52, example-e749fca6b213fe21f43536cc5a1d83dc0397c5604015dc9f393bd2086dbcae84, example-e9a06761f805ebd38f261901a08cefd8d9a7e2ad648d16a1d21fcfeb94e7b4ce, example-cff6ab09d9188f20b21210dbc40500fadf5705093b0875de340dd7553cf3a33f, example-f25a989decc5c357977fa4cbb2214c15cf15286f275b99850bb18c114f4fb73b, example-f5e56e87483f8054b7c1db12d642a63c32b36caf410ef713dd388f59c604c293, example-a0b449d505106555f15ec7c8b99bdb6689bc18a1e9db862019a1c6bff8a2d16a`.
- `opcompat-v1-011` (opcompat-v1-F03/osx), displayed IDs: `none`.
- `opcompat-v1-014` (opcompat-v1-F03/linux), displayed IDs: `example-54f92822e448d5c7c1633ede9176a56d4e1c7354bf9ed2cfb3a9381c2fe14376, example-7df27974797b25d1a000ca98ed99d766c15023775f7d2f210bce3fa01a661097`.
- `opcompat-v1-019` (opcompat-v1-F04/osx), displayed IDs: `example-df0e494352d457d0a19d99c8dd070346d43f2d17261a71c20a10620459028d62, example-685b2b026bc0abfb1dd0bc6a3b5e3c4d2240c0211662829dfb3c59d6b264e485`.
- `opcompat-v1-020` (opcompat-v1-F04/windows), displayed IDs: `example-6650aada822cf387a5574f42e02bc3b42ab84e2c4063c7a0c6366292bbb83d4b`.
### candidate
- `opcompat-v1-004` (opcompat-v1-F01/windows), displayed IDs: `example-72069b7f688efc1ad6e2e48ba1a29800dffdc9c7644f6e8bb17f77864ebda5f2, example-8ce4049b12e6fbdd8ddf55f64fe04680b35071710b29124b53a08b088e26429d, example-38141b4858477c7e64a25e8acd2a173e5a613b28bda28f5fb02c3c377c635d43`.
- `opcompat-v1-005` (opcompat-v1-F01/common), displayed IDs: `example-899be5423d13c42fe2a430cc06b8539e18124b979b0555ed71bd134c2f875375, example-f65291f079140febca69f195c82cdd31fe4080c1b69ce10e3582beb83837f3de, example-d0e3fda8bc712264a0e01e7c181e34b302bb2e5052228147e97b1d9ee79405f8`.
- `opcompat-v1-007` (opcompat-v1-F02/osx), displayed IDs: `none`.
- `opcompat-v1-010` (opcompat-v1-F02/linux), displayed IDs: `example-1701ba64bdde6b5279e26c70c9d8a21f4f44ae584c2ec202143006693cf82b52, example-e9a06761f805ebd38f261901a08cefd8d9a7e2ad648d16a1d21fcfeb94e7b4ce, example-e749fca6b213fe21f43536cc5a1d83dc0397c5604015dc9f393bd2086dbcae84`.
- `opcompat-v1-011` (opcompat-v1-F03/osx), displayed IDs: `none`.
- `opcompat-v1-014` (opcompat-v1-F03/linux), displayed IDs: `example-54f92822e448d5c7c1633ede9176a56d4e1c7354bf9ed2cfb3a9381c2fe14376, example-7df27974797b25d1a000ca98ed99d766c15023775f7d2f210bce3fa01a661097`.
- `opcompat-v1-019` (opcompat-v1-F04/osx), displayed IDs: `example-685b2b026bc0abfb1dd0bc6a3b5e3c4d2240c0211662829dfb3c59d6b264e485, example-df0e494352d457d0a19d99c8dd070346d43f2d17261a71c20a10620459028d62`.
- `opcompat-v1-020` (opcompat-v1-F04/windows), displayed IDs: `example-d16a1c35cef57806a7c7ac819ae912941f17fd3a39cae869a700c8557974d6b2, example-c69f9f2ef51fdde5ea10fad22fa2f1a8f13cee435b2ce9354b69eed777c0be59, example-34ec551605a714d9a5aabb76d979f066b344c34efb17a6f53748b87870ee4078`.
- `opcompat-v1-023` (opcompat-v1-F05/osx), displayed IDs: `example-9bc5ba41e0eb5a49d3d6ba0b8f745482bb8fe2f16c9b118e95b297297e006536, example-0505b8928b6a7ac9d8a476007110acb31944a964fcbc4a0cd2d17c84b517e31a, example-ab19aefda2e3cfb2186012fcf4a4404a8915afdae649c10563a4c0a691662074`.
- `opcompat-v1-025` (opcompat-v1-F05/common), displayed IDs: `example-6a895683594f0e1af4ba619ed22ae064a2f09ad3a4449f8c665780cfcbd44253, example-f22866a28532b383fd5f022f2639743b7bfe2426dba3f84fb7ed62f213601ec3, example-908bc3ab677195e809e96957b618bba3e79acf37c57e15101bfc5aa02db5c01f`.

## Paired bootstrap

- Observed Success@1 gain: `0.1429`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `0.0357`.
- 95% interval: `0.0357` to `0.2857`.

## Gate conditions

- dev-only evidence cannot make a release decision

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
