# Askman release gate

Decision: **inconclusive**

## Inputs and builds

- Generated: `2026-09-27T13:30:38.830676+00:00`
- Evidence scope: `custom-dev-only-exploration`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --main-ref main --candidate-working-tree --dev-only --allow-custom-dev-dataset --custom-dev-manifest docs/reproducibility/artifacts/operational-soft-fit-dev-v1-freeze.json --dev-dataset tests/fixtures/evaluation/operational-soft-fit-dev-v1.json --main-data-dir /tmp/askman-operational-fit-main-data --bundle /tmp/askman-operational-fit-v1-bundle --candidate-config docs/reproducibility/artifacts/operational-soft-fit-dev-v1-treatment-config.json --output-json docs/reproducibility/artifacts/operational-soft-fit-dev-v1-treatment.json --output-markdown docs/reproducibility/artifacts/operational-soft-fit-dev-v1-treatment.md`
- Freeze: `evaluation-v2-release-benchmark-v3`
- Main commit: `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
- Main Cargo.lock SHA-256: `79ee86b480ce00437f814657327b326b725ecd13965d1e958772b5d0ff415990`
- Main binary SHA-256: `e24f91a02008c7e9c6807d4d62c7d8b07170c61197f588e7ab3edf7513cfe38d`
- Candidate commit: `03e60bc72d191154d7d3f6c13a3e8afb06f4b1ee`
- Candidate Cargo.lock SHA-256: `c7eb0288a893ce1f387118cb0fc7370465d2efdfe33de1518ec2715b81c94f76`
- Candidate binary SHA-256: `1f205ef10621602a73ab900d64b3c8a0a746845df4a31c5b26125a5b55055105`
- Freeze manifest SHA-256: `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Independent holdout freeze: `None`
- Gate runner SHA-256: `8175be77b1893a8eaf22b9e6e46629ed1111a3a3a40261fb2d6583e85663b867`
- Candidate bundle: `matching-bundle-v2:38242507ec57eb92a64f9fd96831d49ccc318378f4e644b06c3e302f7b8c0157`
- Candidate bundle tree SHA-256: `54d9abcf54147c1dc199099968e3e7315d3f65a43006925768612328862d7fa6`
- Main data tree SHA-256: `9f29939323a64ca28328388f166451476df7af30113d30a67f7ebf8691467149`
- Main database SHA-256: `d8b83e0e6fc9329d65bf3c5ef42c946babbdc2bdb1897b266ed654814c00d095` (pinned evaluation baseline match: `False`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v4` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `418ac923013146d3b60d920aba50a5d9f69afd3da1c658495c226b648a772daa`
- Holdout dataset SHA-256: `1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418`
- Candidate configuration: `operational-soft-fit-dev-v1-treatment`; `main-compatible` text; `focused-v2` queries; top-8; `retain same-page candidates in the top-k; display the top three after reranking`; ranking `raw cosine distance minus 0.05 per shared query/candidate token plus 0.05 times the fraction of detected action/constraint rules without example-specific evidence`; distance `<= 0.6`; abstention `raw distance cutoff 0.60 plus scoped negation and unsupported-intent guards; operational fit changes ranking only`; fusion `dense candidate pool reranked by 0.05 per shared lexical token and bounded operational fit penalty`.
- Scorer SHA-256: `f1da9807343832411db3d70d6b747a62911c36e6627f9f731982ed8742bc2874`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 13/29 | 18/29 |
| Success@3 | 15/29 | 22/29 |
| Coverage | 39/60 | 41/60 |
| Incorrect answered | 8/23 | 2/24 |
| False answers | 16/31 | 17/31 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 2/7 | 3/7 | 2/7 | 3/7 | 5/8 | 5/8 |
| linux | 5/7 | 4/7 | 6/7 | 6/7 | 4/8 | 3/8 |
| osx | 4/8 | 7/8 | 5/8 | 8/8 | 3/7 | 5/7 |
| windows | 2/7 | 4/7 | 2/7 | 5/7 | 4/8 | 4/8 |

## Scenario-family breakdown

| Family | main Success@1 | retrieval-v2 Success@1 | gain | main incorrect | retrieval-v2 incorrect |
| --- | ---: | ---: | ---: | ---: | ---: |
| 006f336ec75c43e4aa6506727dd85bcd | 1/2 | 2/2 | 0.5000 | 1/2 | 0/2 |
| 049bbef2936a4281849dd0a9bcc78126 | 1/2 | 1/2 | 0.0000 | 0/2 | 0/2 |
| 1a0eaa86d98f49d8a1603c041f1afef2 | 1/3 | 3/3 | 0.6667 | 1/3 | 0/3 |
| 32b63a99073448b0bdf3ae011c63577e | 1/3 | 1/3 | 0.0000 | 0/1 | 0/1 |
| 5722a11df4b84b89844aea00de7a0d5c | 0/2 | 1/2 | 0.5000 | 1/1 | 0/1 |
| 63cb71cbafd94b539d89042bc5c4ad09 | 0/2 | 0/2 | 0.0000 | 0/0 | 1/1 |
| 75ae6a8ad3b54a3b965318238ac62d9f | 1/2 | 1/2 | 0.0000 | 1/2 | 1/2 |
| 823861f9273b4cdcafb85e8fe5ca9082 | 1/3 | 2/3 | 0.3333 | 2/3 | 0/3 |
| ba749ef366884d319d45a7a63780f9a1 | 1/2 | 1/2 | 0.0000 | 0/1 | 0/1 |
| beb62b7e9d0e478f85052b777ebdf0c1 | 3/3 | 2/3 | -0.3333 | 0/3 | 0/3 |
| ca9873f90e604121b6678f02cc10e425 | 1/3 | 2/3 | 0.3333 | 2/3 | 0/3 |
| f110b7753e724685a36322e249d6c664 | 2/2 | 2/2 | 0.0000 | 0/2 | 0/2 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 97.816 ms | 98.661 ms | 237,847,248 B | 268,714,680 B |
| warmed query | 97.038 ms | 97.231 ms | 236,143,288 B | 237,159,096 B |

## Execution

- Main failed CLI runs: `0`.
- Candidate failed CLI runs: `0`.

## Failure examples

### main
- `dev_66fc786d876d4ba7b93dc61afc712c91` (32b63a99073448b0bdf3ae011c63577e/common), displayed IDs: `none`.
- `dev_75eac8f0c9b44ed1aea261f462e00f92` (32b63a99073448b0bdf3ae011c63577e/common), displayed IDs: `none`.
- `dev_092c16d6323247649d0ae98abf7f1ca9` (32b63a99073448b0bdf3ae011c63577e/common), displayed IDs: `example-347ce66a0c235ac4af6eb14f94c5bd5bc61b1fbb3603460f2c2537bcb0c386cc`.
- `dev_cb46dbcf3dda4a77b57586084a085eb7` (5722a11df4b84b89844aea00de7a0d5c/common), displayed IDs: `example-38141b4858477c7e64a25e8acd2a173e5a613b28bda28f5fb02c3c377c635d43`.
- `dev_761615b42d4a4ab5aced0a7dfc5d9488` (5722a11df4b84b89844aea00de7a0d5c/common), displayed IDs: `none`.
- `dev_82234d6fb05947dd9a39e5ec58a234fc` (5722a11df4b84b89844aea00de7a0d5c/common), displayed IDs: `example-8cf1e46e2765d3ba5e150fb891b7d7d1f9d8ac8cf4af04d09a40970be870a49d, example-c5fcd87e47e9d553fdb1891154e8176aabb962d6465da156970ef98684e31805, example-e16b86c8a06212d4e22ae6ac815b678ea96ed7fa03663a872cce397b804f0a85, example-8ce4049b12e6fbdd8ddf55f64fe04680b35071710b29124b53a08b088e26429d, example-72069b7f688efc1ad6e2e48ba1a29800dffdc9c7644f6e8bb17f77864ebda5f2, example-25c6586273d26bc16764aa1e96f645b310b059f28268a939024d9e26ee748892`.
- `dev_5b803defce544c7db8687fd8f5e4b96c` (5722a11df4b84b89844aea00de7a0d5c/common), displayed IDs: `example-76f2d329d91d6a6ac8b1ff660eae27a36e5968889bbe20b3a6dab74a221a52b5`.
- `dev_d76930342faa4db2b29a436c2a0fd1ac` (75ae6a8ad3b54a3b965318238ac62d9f/common), displayed IDs: `example-c7e7560a61cc444906eb6f2eb172fd18d2dda57f6d72cc794370fb3889a77238, example-b1339e30586a6a791eb124959561905d0f2c467a62a74a4faa6e2cee104a8651, example-960cbf5056bae848f6fa5828c3c9dd960b95dff60228d904620f77c3d0b47f69, example-4d3c37d3247edb0edb4cb01aa08ae31b7e9baf06d44e985aff0a1f0e807ad8fc, example-347ce66a0c235ac4af6eb14f94c5bd5bc61b1fbb3603460f2c2537bcb0c386cc`.
- `dev_e971dd68e06843388dd4aca532c40089` (75ae6a8ad3b54a3b965318238ac62d9f/common), displayed IDs: `example-9401e615e42aac59e1c88665393b3e85c5bd4766b64dd13b1d3e1f8fb044d20c, example-5b19239e07b5398803ab71677bcf14eb9a2c8698a34f6cf280a47deaaa13f842, example-f65291f079140febca69f195c82cdd31fe4080c1b69ce10e3582beb83837f3de, example-d0e3fda8bc712264a0e01e7c181e34b302bb2e5052228147e97b1d9ee79405f8, example-4da8541e1d6bb3172db5aeb6d2a5d677f7ce07c1402b88cf3406b588c16ade24, example-5d09c75a518514e31f768a34add321aa8ffd2802819fce2b3c674266bbe18640, example-d99ee371ddcfb0d3bacff56d1e85a15e77d4fd1ebf9c45c1db576f1a198978c1`.
- `dev_b110f3afdef74c46b0d76f263a7a6ec6` (75ae6a8ad3b54a3b965318238ac62d9f/common), displayed IDs: `example-9401e615e42aac59e1c88665393b3e85c5bd4766b64dd13b1d3e1f8fb044d20c, example-d0e3fda8bc712264a0e01e7c181e34b302bb2e5052228147e97b1d9ee79405f8, example-f65291f079140febca69f195c82cdd31fe4080c1b69ce10e3582beb83837f3de, example-5d09c75a518514e31f768a34add321aa8ffd2802819fce2b3c674266bbe18640, example-5b19239e07b5398803ab71677bcf14eb9a2c8698a34f6cf280a47deaaa13f842, example-d99ee371ddcfb0d3bacff56d1e85a15e77d4fd1ebf9c45c1db576f1a198978c1, example-78126bf8914de541904d6bdad5a11e75e704ea53d4cd96c02196623b5dcbebfd`.
### candidate
- `dev_66fc786d876d4ba7b93dc61afc712c91` (32b63a99073448b0bdf3ae011c63577e/common), displayed IDs: `none`.
- `dev_75eac8f0c9b44ed1aea261f462e00f92` (32b63a99073448b0bdf3ae011c63577e/common), displayed IDs: `none`.
- `dev_092c16d6323247649d0ae98abf7f1ca9` (32b63a99073448b0bdf3ae011c63577e/common), displayed IDs: `example-347ce66a0c235ac4af6eb14f94c5bd5bc61b1fbb3603460f2c2537bcb0c386cc`.
- `dev_761615b42d4a4ab5aced0a7dfc5d9488` (5722a11df4b84b89844aea00de7a0d5c/common), displayed IDs: `none`.
- `dev_82234d6fb05947dd9a39e5ec58a234fc` (5722a11df4b84b89844aea00de7a0d5c/common), displayed IDs: `example-8cf1e46e2765d3ba5e150fb891b7d7d1f9d8ac8cf4af04d09a40970be870a49d, example-e16b86c8a06212d4e22ae6ac815b678ea96ed7fa03663a872cce397b804f0a85, example-c5fcd87e47e9d553fdb1891154e8176aabb962d6465da156970ef98684e31805`.
- `dev_5b803defce544c7db8687fd8f5e4b96c` (5722a11df4b84b89844aea00de7a0d5c/common), displayed IDs: `example-76f2d329d91d6a6ac8b1ff660eae27a36e5968889bbe20b3a6dab74a221a52b5, example-376799c4c44eb53e83e7abc95787b370bf11b82778628c98b5a369c61702957e`.
- `dev_d76930342faa4db2b29a436c2a0fd1ac` (75ae6a8ad3b54a3b965318238ac62d9f/common), displayed IDs: `example-347ce66a0c235ac4af6eb14f94c5bd5bc61b1fbb3603460f2c2537bcb0c386cc, example-c7e7560a61cc444906eb6f2eb172fd18d2dda57f6d72cc794370fb3889a77238, example-ce8d1ab16002f7cdda6ede7ad1a754f9e442cd1216b97d4346fed35e325aa730`.
- `dev_e971dd68e06843388dd4aca532c40089` (75ae6a8ad3b54a3b965318238ac62d9f/common), displayed IDs: `example-9401e615e42aac59e1c88665393b3e85c5bd4766b64dd13b1d3e1f8fb044d20c, example-d99ee371ddcfb0d3bacff56d1e85a15e77d4fd1ebf9c45c1db576f1a198978c1, example-5b19239e07b5398803ab71677bcf14eb9a2c8698a34f6cf280a47deaaa13f842`.
- `dev_b110f3afdef74c46b0d76f263a7a6ec6` (75ae6a8ad3b54a3b965318238ac62d9f/common), displayed IDs: `example-9401e615e42aac59e1c88665393b3e85c5bd4766b64dd13b1d3e1f8fb044d20c, example-d0e3fda8bc712264a0e01e7c181e34b302bb2e5052228147e97b1d9ee79405f8, example-f65291f079140febca69f195c82cdd31fe4080c1b69ce10e3582beb83837f3de`.
- `dev_f7c87f2011c64c5cbd06507c092b829e` (ba749ef366884d319d45a7a63780f9a1/linux), displayed IDs: `none`.

## Paired bootstrap

- Observed Success@1 gain: `0.1724`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `0.0345`.
- 95% interval: `0.0000` to `0.3448`.

## Gate conditions

- Success@1 regressed in: beb62b7e9d0e478f85052b777ebdf0c1
- overall false_answers_on_unanswerable regressed
- false_answers_on_unanswerable regressed on platform osx
- dev-only evidence cannot make a release decision

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
