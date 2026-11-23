# Askman release gate

Decision: **inconclusive**

## Inputs and builds

- Generated: `2026-09-27T10:52:48.006731+00:00`
- Evidence scope: `release-gate`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --candidate-working-tree --main-data-dir /tmp/askman-goal.Fk5Zkh/main-import-home/Library/Application Support/askman --bundle /tmp/askman-goal.Fk5Zkh/bundle-final-v2 --allow-holdout --independent-holdout-manifest tests/fixtures/evaluation/fresh-holdout-v3.manifest.json --holdout-dataset tests/fixtures/evaluation/fresh-holdout-v3.json --warmup-queries 5 --warm-queries 30 --output-json docs/reproducibility/artifacts/main-vs-retrieval-v2-focused-query-rules-fresh-holdout-v3.json --output-markdown docs/reproducibility/artifacts/main-vs-retrieval-v2-focused-query-rules-fresh-holdout-v3.md`
- Freeze: `evaluation-v2-release-benchmark-v3`
- Main commit: `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
- Main Cargo.lock SHA-256: `79ee86b480ce00437f814657327b326b725ecd13965d1e958772b5d0ff415990`
- Main binary SHA-256: `e24f91a02008c7e9c6807d4d62c7d8b07170c61197f588e7ab3edf7513cfe38d`
- Candidate commit: `03e60bc72d191154d7d3f6c13a3e8afb06f4b1ee`
- Candidate Cargo.lock SHA-256: `c7eb0288a893ce1f387118cb0fc7370465d2efdfe33de1518ec2715b81c94f76`
- Candidate binary SHA-256: `e727941c9efbfadc0ba4bd89885d880d8f3b6ca27d663f88c502e89c4d91e1b5`
- Freeze manifest SHA-256: `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Independent holdout freeze: `fresh-holdout-v3-freeze-2026-09-27`
- Gate runner SHA-256: `85c0250bc58050e377bc344501f40477a094dedd3ead1a8fd85e883c4e701c8f`
- Candidate bundle: `matching-bundle-v2:8e53794515abdcaa0e304fb3ea533144461ae7018f87264c2fabcbd3fee191e4`
- Candidate bundle tree SHA-256: `082553b9446a6bf75aa0cdd2506ff283fbd1dc36ec40fc8333789fd17c74bfbf`
- Main data tree SHA-256: `8dbd6badbb01e78b321608ebfb425b70eec1d7674d41991b3e4913c67b4033f8`
- Main database SHA-256: `ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db` (pinned evaluation baseline match: `True`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v3` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `216c0e26f24fda7df197011be4f8add33b6852b7907b32966b0c77e0a26c947d`
- Holdout dataset SHA-256: `b4f25cccf30f5b05232c09d6b1c91e0b914b82e206edb9256a74847b7ed4450d`
- Candidate configuration: `focused-v2-same-page-cutoff-060-lexical-005-v1`; `main-compatible` text; `focused-v2` queries; top-8; `retain same-page candidates in the top-k; display the top three after reranking`; ranking `raw cosine distance minus 0.05 per shared query/candidate token`; distance `<= 0.6`; abstention `raw distance cutoff 0.60 plus scoped negation and unsupported-intent guards`; fusion `dense candidate pool reranked by 0.05 per shared lexical token`.
- Scorer SHA-256: `04127320c26df81b1f8be4dbbd9a26ed67d3aad34f2a327bcc0efdcdb2929f4f`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 30/60 | 46/60 |
| Success@3 | 39/60 | 52/60 |
| Coverage | 52/120 | 55/120 |
| Incorrect answered | 12/51 | 2/54 |
| False answers | 1/60 | 1/60 |

## Split-specific quality

| Split | Metric | main | retrieval-v2 |
| --- | --- | ---: | ---: |
| dev | Success@1 | 18/30 | 28/30 |
| dev | Success@3 | 23/30 | 30/30 |
| dev | False answers | 1/30 | 1/30 |
| holdout | Success@1 | 12/30 | 18/30 |
| holdout | Success@3 | 16/30 | 22/30 |
| holdout | False answers | 0/30 | 0/30 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 13/18 | 13/18 | 15/18 | 14/18 | 0/12 | 0/12 |
| linux | 9/17 | 13/17 | 13/17 | 15/17 | 0/13 | 0/13 |
| osx | 6/13 | 10/13 | 7/13 | 12/13 | 0/17 | 0/17 |
| windows | 2/12 | 10/12 | 4/12 | 11/12 | 1/18 | 1/18 |

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
| fresh-v3-clean-common-cp-extension-interactive | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-common-find-exclude-site-packages | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-common-find-exec-line-count | 0/1 | 0/1 | 0.0000 | 1/1 | 1/1 |
| fresh-v3-clean-common-find-ext-csv-reports | 0/1 | 1/1 | 1.0000 | 0/1 | 0/1 |
| fresh-v3-clean-common-find-ext-log-workspace | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-common-find-ext-markdown-notes | 1/1 | 0/1 | -1.0000 | 0/1 | 0/0 |
| fresh-v3-clean-common-find-ext-png-assets | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-common-find-ext-toml-project | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-common-unsupported-change-owner | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-common-unsupported-cpu-temperature | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-common-unsupported-create-zip | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-common-unsupported-list-open-ports | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-common-unsupported-start-web-server | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-linux-apt-inspect-package | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-linux-apt-install-package | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-linux-apt-refresh-index | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-linux-apt-search-description | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-linux-find-ext-csv-linux | 0/1 | 1/1 | 1.0000 | 0/0 | 0/1 |
| fresh-v3-clean-linux-find-ext-log-linux | 0/1 | 0/1 | 0.0000 | 0/0 | 0/1 |
| fresh-v3-clean-linux-find-ext-python-linux | 0/1 | 0/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-linux-unsupported-linux-docker-run | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-linux-unsupported-linux-firewall | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-linux-unsupported-linux-kill-process | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-linux-unsupported-linux-smb-mount | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-osx-mdfind-content-term | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-osx-mdfind-only-folder | 0/1 | 0/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-osx-open-associated-file | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-osx-open-extension-files | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-osx-pbcopy-file | 0/1 | 1/1 | 1.0000 | 1/1 | 0/1 |
| fresh-v3-clean-osx-pbpaste-to-file | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-osx-say-custom-voice-rate | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-osx-screencapture-selected-area | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-osx-unsupported-mac-bluetooth-pair | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-osx-unsupported-mac-change-volume | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-osx-unsupported-mac-create-apfs-volume | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-osx-unsupported-mac-install-homebrew | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-osx-unsupported-mac-list-fonts | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-windows-copy-extension-csv | 0/1 | 0/1 | 0.0000 | 1/1 | 0/1 |
| fresh-v3-clean-windows-copy-extension-images | 0/1 | 0/1 | 0.0000 | 1/1 | 1/1 |
| fresh-v3-clean-windows-move-another-drive-file | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| fresh-v3-clean-windows-move-c-drive-to-d-drive-file | 0/1 | 1/1 | 1.0000 | 0/0 | 0/1 |
| fresh-v3-clean-windows-move-cross-drive-directory | 0/1 | 1/1 | 1.0000 | 0/1 | 0/1 |
| fresh-v3-clean-windows-move-cross-drive-no-prompt | 0/1 | 1/1 | 1.0000 | 1/1 | 0/1 |
| fresh-v3-clean-windows-move-drive-letter-relocation | 0/1 | 1/1 | 1.0000 | 0/0 | 0/1 |
| fresh-v3-clean-windows-unsupported-windows-acl | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-windows-unsupported-windows-firewall | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-windows-unsupported-windows-map-drive | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-clean-windows-unsupported-windows-scheduled-task | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-common-login-name | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-common-working-directory | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-linux-kernel-modules | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-linux-smart-health | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-linux-swap-file | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-linux-usb-devices | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-osx-default-shell | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-osx-filevault | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-windows-bitlocker | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-windows-optional-features | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-windows-remote-desktop | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-v3-supp-windows-restore-point | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 94.078 ms | 100.455 ms | 237,683,384 B | 283,656,960 B |
| holdout fresh | 108.766 ms | 95.895 ms | 238,191,312 B | 237,683,384 B |
| warmed query | 106.465 ms | 92.923 ms | 236,765,880 B | 236,323,512 B |

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
- `fresh-v3-clean-common-013` (fresh-v3-clean-common-cp-extension-interactive/common), displayed IDs: `none`.
- `fresh-v3-clean-common-010` (fresh-v3-clean-common-find-exec-line-count/common), displayed IDs: `example-b1339e30586a6a791eb124959561905d0f2c467a62a74a4faa6e2cee104a8651`.
### candidate
- `dev-v2r1-devwindows-unsupported-a-04` (dev39-windows-unsupported-registry/windows), displayed IDs: `example-34ec551605a714d9a5aabb76d979f066b344c34efb17a6f53748b87870ee4078`.
- `fresh-v3-clean-common-013` (fresh-v3-clean-common-cp-extension-interactive/common), displayed IDs: `none`.
- `fresh-v3-clean-common-010` (fresh-v3-clean-common-find-exec-line-count/common), displayed IDs: `example-b1339e30586a6a791eb124959561905d0f2c467a62a74a4faa6e2cee104a8651, example-5b19239e07b5398803ab71677bcf14eb9a2c8698a34f6cf280a47deaaa13f842`.
- `fresh-v3-clean-common-003` (fresh-v3-clean-common-find-ext-markdown-notes/common), displayed IDs: `none`.
- `fresh-v3-clean-common-004` (fresh-v3-clean-common-find-ext-png-assets/common), displayed IDs: `none`.
- `fresh-v3-clean-linux-007` (fresh-v3-clean-linux-apt-install-package/linux), displayed IDs: `none`.
- `fresh-v3-clean-linux-004` (fresh-v3-clean-linux-apt-refresh-index/linux), displayed IDs: `none`.
- `fresh-v3-clean-osx-007` (fresh-v3-clean-osx-open-associated-file/osx), displayed IDs: `none`.
- `fresh-v3-clean-windows-007` (fresh-v3-clean-windows-copy-extension-images/windows), displayed IDs: `example-234cb44d418053d5b2c7b67e416745fc67d8860d980e2237179f13b052680153, example-d618ff9680fc746c36140ae801d0275fbf049ae30a49a60dccca4bcd28de4dba, example-e3c3c406155b49077479b68066a9f86636c2294945c631feff0bdecfcb2f1892`.

## Paired bootstrap

- Observed Success@1 gain: `0.2667`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `0.1667`.
- 95% interval: `0.1500` to `0.3833`.

## Independent holdout check

- Holdout Success@1 gain: `0.2000`.
- One-sided 95% lower bound: `0.0667`.
- Independent holdout decision: **inconclusive**.

## Gate conditions

- Success@1 regressed in: fresh-v3-clean-common-find-ext-markdown-notes
- success_at_3 regressed on platform common
- incorrect_answered_tasks regressed on platform common
- independent holdout success_at_3 regressed on platform common
- independent holdout incorrect_answered_tasks regressed on platform common

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
