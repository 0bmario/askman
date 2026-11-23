# Askman release gate

Decision: **inconclusive**

## Inputs and builds

- Generated: `2026-09-27T13:57:44.380160+00:00`
- Evidence scope: `custom-dev-only-exploration`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --main-data-dir /tmp/askman-operational-fit-main-data --bundle /tmp/askman-operational-fit-v1-bundle --dev-only --allow-custom-dev-dataset --custom-dev-manifest docs/reproducibility/artifacts/dense-budget-dev-v1-freeze.json --dev-dataset tests/fixtures/evaluation/dense-budget-dev-v1.json --candidate-working-tree --candidate-config docs/reproducibility/artifacts/dense-budget-dev-v1-treatment-config.json --output-json docs/reproducibility/artifacts/dense-budget-dev-v1-treatment.json --output-markdown docs/reproducibility/artifacts/dense-budget-dev-v1-treatment.md`
- Freeze: `evaluation-v2-release-benchmark-v3`
- Main commit: `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
- Main Cargo.lock SHA-256: `79ee86b480ce00437f814657327b326b725ecd13965d1e958772b5d0ff415990`
- Main binary SHA-256: `e24f91a02008c7e9c6807d4d62c7d8b07170c61197f588e7ab3edf7513cfe38d`
- Candidate commit: `03e60bc72d191154d7d3f6c13a3e8afb06f4b1ee`
- Candidate Cargo.lock SHA-256: `c7eb0288a893ce1f387118cb0fc7370465d2efdfe33de1518ec2715b81c94f76`
- Candidate binary SHA-256: `affea3983ac89afb79f05d5ef43e456834d470a9b5444f204b53271804b412c4`
- Freeze manifest SHA-256: `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Independent holdout freeze: `None`
- Gate runner SHA-256: `8d99605b66d208b66bd4551120f3853aa93005a55da3d65d8cceca97bace12ea`
- Candidate bundle: `matching-bundle-v2:38242507ec57eb92a64f9fd96831d49ccc318378f4e644b06c3e302f7b8c0157`
- Candidate bundle tree SHA-256: `54d9abcf54147c1dc199099968e3e7315d3f65a43006925768612328862d7fa6`
- Main data tree SHA-256: `9f29939323a64ca28328388f166451476df7af30113d30a67f7ebf8691467149`
- Main database SHA-256: `d8b83e0e6fc9329d65bf3c5ef42c946babbdc2bdb1897b266ed654814c00d095` (pinned evaluation baseline match: `False`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v4` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `cdb3c6567c5575b007ad0581d0f84d66fcf8237b3f6a8d839dfdddd7d01c0297`
- Holdout dataset SHA-256: `1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418`
- Candidate configuration: `dense-budget-dev-v1-treatment-budget-16`; `main-compatible` text; `focused-v2` queries; top-16; `retain same-page candidates in the top-k; display the top three after reranking`; ranking `raw cosine distance minus 0.05 per shared query/candidate token`; distance `<= 0.6`; abstention `raw distance cutoff 0.60 plus scoped negation and unsupported-intent guards`; fusion `dense candidate pool reranked by 0.05 per shared lexical token`.
- Scorer SHA-256: `f1da9807343832411db3d70d6b747a62911c36e6627f9f731982ed8742bc2874`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 16/26 | 20/26 |
| Success@3 | 17/26 | 21/26 |
| Coverage | 46/60 | 44/60 |
| Incorrect answered | 5/22 | 1/22 |
| False answers | 24/34 | 22/34 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 6/8 | 6/8 | 7/8 | 7/8 | 2/7 | 2/7 |
| linux | 4/7 | 5/7 | 4/7 | 5/7 | 5/8 | 5/8 |
| osx | 5/6 | 6/6 | 5/6 | 6/6 | 8/9 | 8/9 |
| windows | 1/5 | 3/5 | 1/5 | 3/5 | 9/10 | 7/10 |

## Scenario-family breakdown

| Family | main Success@1 | retrieval-v2 Success@1 | gain | main incorrect | retrieval-v2 incorrect |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0d80175810984ad7bfe142762d7a0447 | 1/2 | 2/2 | 0.5000 | 1/2 | 0/2 |
| 0e5b3b499bd74b3aa8bc2cb4c0a38f0d | 2/3 | 2/3 | 0.0000 | 0/3 | 0/3 |
| 1a4e9adf0ce74b4f845d692798a14b59 | 2/2 | 2/2 | 0.0000 | 0/2 | 0/2 |
| 46a0c178dc554de59eadee7c6f40b10b | 0/3 | 1/3 | 0.3333 | 1/1 | 0/1 |
| 4addbcd762474a11b07074b6aa37ed8b | 2/2 | 2/2 | 0.0000 | 0/2 | 0/2 |
| 6a7de120cd484640a33ee6e16fdd3839 | 2/3 | 2/3 | 0.0000 | 1/3 | 1/3 |
| 9df0dcd9649f48daabbc0bb257a4a78a | 1/3 | 1/3 | 0.0000 | 0/1 | 0/1 |
| a8342bab79c64eb9ae7804496802b0f2 | 0/1 | 1/1 | 1.0000 | 1/1 | 0/1 |
| ab480a38588b4c7e853e3a46f1823b45 | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| c4792170a64846e5a1b813ec0203fd7d | 2/2 | 2/2 | 0.0000 | 0/2 | 0/2 |
| de467238082b4c25bab8d0db77ba875a | 3/3 | 3/3 | 0.0000 | 0/3 | 0/3 |
| f85e0207fb8c4b199771b6e58563bf0d | 1/2 | 2/2 | 0.5000 | 1/2 | 0/2 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 93.300 ms | 90.298 ms | 237,503,232 B | 254,034,616 B |
| warmed query | 89.150 ms | 88.146 ms | 236,618,424 B | 237,470,416 B |

## Execution

- Main failed CLI runs: `0`.
- Candidate failed CLI runs: `0`.

## Failure examples

### main
- `budget_dev_e0163528f25f408391d3394e8aa624b8` (6a7de120cd484640a33ee6e16fdd3839/common), displayed IDs: `example-ad09edccd5904d5046ee20a47a60b0f07ce8a4eaefee4d12526a2110a775a5ff, example-37cdfdfe2d6c22084e82141bb12c6bbf98f22ec017b221c38c1939fa7bd5b201`.
- `budget_dev_24903b6ad9e94d6bbebff0c7ac6ef459` (c4792170a64846e5a1b813ec0203fd7d/common), displayed IDs: `example-df0e494352d457d0a19d99c8dd070346d43f2d17261a71c20a10620459028d62`.
- `budget_dev_1c39fabc53254a3b90af6a60d4cdff87` (0e5b3b499bd74b3aa8bc2cb4c0a38f0d/common), displayed IDs: `example-78126bf8914de541904d6bdad5a11e75e704ea53d4cd96c02196623b5dcbebfd, example-d99ee371ddcfb0d3bacff56d1e85a15e77d4fd1ebf9c45c1db576f1a198978c1, example-5d09c75a518514e31f768a34add321aa8ffd2802819fce2b3c674266bbe18640, example-4da8541e1d6bb3172db5aeb6d2a5d677f7ce07c1402b88cf3406b588c16ade24, example-d0e3fda8bc712264a0e01e7c181e34b302bb2e5052228147e97b1d9ee79405f8, example-f65291f079140febca69f195c82cdd31fe4080c1b69ce10e3582beb83837f3de, example-9401e615e42aac59e1c88665393b3e85c5bd4766b64dd13b1d3e1f8fb044d20c`.
- `budget_dev_9d296e05ee4e4d609ae0464bb2e472c5` (9df0dcd9649f48daabbc0bb257a4a78a/linux), displayed IDs: `none`.
- `budget_dev_d5353dda678d4abc9d57b4faf5773fb0` (9df0dcd9649f48daabbc0bb257a4a78a/linux), displayed IDs: `none`.
- `budget_dev_2878969f1c8749c79fda23a56a63f49e` (9df0dcd9649f48daabbc0bb257a4a78a/linux), displayed IDs: `example-e1d50ec8bcbdbb1cde2d2d97c841c00ee709fc61c9e125b61d5e6e1cea601d16, example-26a75f510d23eade1920023e9d21690e523c6712534627e709bc9c6acf4c41a3, example-abeeeec14691630cd2bbb82659839005eb339a0e35a5c4c36f10ec358cab835d, example-54f92822e448d5c7c1633ede9176a56d4e1c7354bf9ed2cfb3a9381c2fe14376, example-3361b1ecf86583a27532ca13f6d759f054da6534169346204e061c8cf5edd9fb, example-7df27974797b25d1a000ca98ed99d766c15023775f7d2f210bce3fa01a661097, example-5270e7367ac85aacdf86577d153a225237069a6d0d8a97e0eb86ee127154898b`.
- `budget_dev_43a453d4f4ae4eac86eb6fb01be33392` (f85e0207fb8c4b199771b6e58563bf0d/linux), displayed IDs: `example-fde36aeb068ae85eb35667e80ad9fc1f2b8f79313764a2e6f16ef046e9409b40, example-ca1e1eb99dc4ed5ed7666c3464df94fa1438a7f92ffcd52d8626f982c0f51f0b, example-919b9bbb472e6c0d858c0468f2e80a835c266af944209da72656a19382fc61d5`.
- `budget_dev_3134e36db5cc450197479d6d51a8669a` (f85e0207fb8c4b199771b6e58563bf0d/linux), displayed IDs: `example-fde36aeb068ae85eb35667e80ad9fc1f2b8f79313764a2e6f16ef046e9409b40, example-919b9bbb472e6c0d858c0468f2e80a835c266af944209da72656a19382fc61d5, example-ca1e1eb99dc4ed5ed7666c3464df94fa1438a7f92ffcd52d8626f982c0f51f0b, example-9c3f58af214e9a579b9f6943bc021cdb16a28ef87eba18ff5d7bde38affe3e85, example-e289813d18091e93b087eefe1f3b3a028a681047f0c372e67caea94d89bb2bd8`.
- `budget_dev_c7e04d505aad47bda1de14f7684228bc` (f85e0207fb8c4b199771b6e58563bf0d/linux), displayed IDs: `example-fde36aeb068ae85eb35667e80ad9fc1f2b8f79313764a2e6f16ef046e9409b40`.
- `budget_dev_b7bb83d6f02c4be4a95a466726aef242` (1a4e9adf0ce74b4f845d692798a14b59/linux), displayed IDs: `example-011841c17bb47a0959c6f904421fe8999ec8524178684750864e7d14b518fafc, example-c271943f3dad6797361b9e6b7fefb432da846eb2bf306addf579d49fab7474ba`.
### candidate
- `budget_dev_e0163528f25f408391d3394e8aa624b8` (6a7de120cd484640a33ee6e16fdd3839/common), displayed IDs: `example-0c35c6716b085f5e02bfb833a3a66ddd6fe9d7a66107f6a526b2dbdd025a3069, example-ad09edccd5904d5046ee20a47a60b0f07ce8a4eaefee4d12526a2110a775a5ff`.
- `budget_dev_24903b6ad9e94d6bbebff0c7ac6ef459` (c4792170a64846e5a1b813ec0203fd7d/common), displayed IDs: `example-df0e494352d457d0a19d99c8dd070346d43f2d17261a71c20a10620459028d62`.
- `budget_dev_1c39fabc53254a3b90af6a60d4cdff87` (0e5b3b499bd74b3aa8bc2cb4c0a38f0d/common), displayed IDs: `example-78126bf8914de541904d6bdad5a11e75e704ea53d4cd96c02196623b5dcbebfd, example-d99ee371ddcfb0d3bacff56d1e85a15e77d4fd1ebf9c45c1db576f1a198978c1, example-d0e3fda8bc712264a0e01e7c181e34b302bb2e5052228147e97b1d9ee79405f8`.
- `budget_dev_9d296e05ee4e4d609ae0464bb2e472c5` (9df0dcd9649f48daabbc0bb257a4a78a/linux), displayed IDs: `none`.
- `budget_dev_d5353dda678d4abc9d57b4faf5773fb0` (9df0dcd9649f48daabbc0bb257a4a78a/linux), displayed IDs: `none`.
- `budget_dev_2878969f1c8749c79fda23a56a63f49e` (9df0dcd9649f48daabbc0bb257a4a78a/linux), displayed IDs: `example-26a75f510d23eade1920023e9d21690e523c6712534627e709bc9c6acf4c41a3, example-abeeeec14691630cd2bbb82659839005eb339a0e35a5c4c36f10ec358cab835d, example-e1d50ec8bcbdbb1cde2d2d97c841c00ee709fc61c9e125b61d5e6e1cea601d16`.
- `budget_dev_3134e36db5cc450197479d6d51a8669a` (f85e0207fb8c4b199771b6e58563bf0d/linux), displayed IDs: `example-2abf38a4f04947106d31a574559f7e21ec43c8c60d7e042916b6e5f324cb91f4, example-f632ec772f5c9ae6d66d4358b393e057fffaf9652e2a7802e6059fefcd49f156, example-fde36aeb068ae85eb35667e80ad9fc1f2b8f79313764a2e6f16ef046e9409b40`.
- `budget_dev_c7e04d505aad47bda1de14f7684228bc` (f85e0207fb8c4b199771b6e58563bf0d/linux), displayed IDs: `example-2abf38a4f04947106d31a574559f7e21ec43c8c60d7e042916b6e5f324cb91f4, example-fde36aeb068ae85eb35667e80ad9fc1f2b8f79313764a2e6f16ef046e9409b40`.
- `budget_dev_b7bb83d6f02c4be4a95a466726aef242` (1a4e9adf0ce74b4f845d692798a14b59/linux), displayed IDs: `example-635808eeb22bdbe61688c222a223c384429fa1d9dd798154c7937d5d3ad28ade, example-011841c17bb47a0959c6f904421fe8999ec8524178684750864e7d14b518fafc, example-da5da8ecc41b766f610565f3a5609529202c2ed456f1310668ea319630ced4c4`.
- `budget_dev_1c300b7dfce34e678e52d74ece077047` (1a4e9adf0ce74b4f845d692798a14b59/linux), displayed IDs: `example-e9a06761f805ebd38f261901a08cefd8d9a7e2ad648d16a1d21fcfeb94e7b4ce, example-cff6ab09d9188f20b21210dbc40500fadf5705093b0875de340dd7553cf3a33f, example-e749fca6b213fe21f43536cc5a1d83dc0397c5604015dc9f393bd2086dbcae84`.

## Paired bootstrap

- Observed Success@1 gain: `0.1538`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `0.0385`.
- 95% interval: `0.0385` to `0.3077`.

## Gate conditions

- dev-only evidence cannot make a release decision

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
