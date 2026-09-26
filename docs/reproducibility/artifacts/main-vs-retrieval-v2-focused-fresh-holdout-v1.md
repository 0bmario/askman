# Askman release gate

Decision: **inconclusive**

## Inputs and builds

- Generated: `2026-09-26T16:36:10.084769+00:00`
- Evidence scope: `release-gate`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --candidate-ref 3494a11c57c31045bb9897c9fa187d768e18ebcb --main-data-dir /tmp/askman-goal.Fk5Zkh/main-import-home/Library/Application Support/askman --bundle /tmp/askman-goal.Fk5Zkh/bundle-final-v2 --allow-holdout --independent-holdout-manifest tests/fixtures/evaluation/fresh-holdout-v1.manifest.json --holdout-dataset tests/fixtures/evaluation/fresh-holdout-v1.json --output-json /tmp/askman-focused-fresh-holdout-v1.json --output-markdown /tmp/askman-focused-fresh-holdout-v1.md`
- Freeze: `evaluation-v2-release-benchmark-v3`
- Main commit: `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
- Main Cargo.lock SHA-256: `79ee86b480ce00437f814657327b326b725ecd13965d1e958772b5d0ff415990`
- Main binary SHA-256: `e24f91a02008c7e9c6807d4d62c7d8b07170c61197f588e7ab3edf7513cfe38d`
- Candidate commit: `3494a11c57c31045bb9897c9fa187d768e18ebcb`
- Candidate Cargo.lock SHA-256: `c7eb0288a893ce1f387118cb0fc7370465d2efdfe33de1518ec2715b81c94f76`
- Candidate binary SHA-256: `2e03c4d99601b9d14f1dc0ad63545c12b274ddc5356abbaa043d8b914ce80521`
- Freeze manifest SHA-256: `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Independent holdout freeze: `fresh-holdout-v1-freeze-2026-09-26`
- Gate runner SHA-256: `773e464f4a90fa1788e1b7a9f2f8f1d7d70b49b0cdc502c6124e8db71267a2a8`
- Candidate bundle: `matching-bundle-v2:8e53794515abdcaa0e304fb3ea533144461ae7018f87264c2fabcbd3fee191e4`
- Candidate bundle tree SHA-256: `082553b9446a6bf75aa0cdd2506ff283fbd1dc36ec40fc8333789fd17c74bfbf`
- Main data tree SHA-256: `8dbd6badbb01e78b321608ebfb425b70eec1d7674d41991b3e4913c67b4033f8`
- Main database SHA-256: `ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db` (pinned evaluation baseline match: `True`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v3` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `216c0e26f24fda7df197011be4f8add33b6852b7907b32966b0c77e0a26c947d`
- Holdout dataset SHA-256: `7fe11e153b64941c91233b756543487ebdd34e17bcca7b935a55f8f16a6fb2a0`
- Candidate retrieval: `main-compatible` text, `focused-v1` queries, distance `<= 0.55`, fusion `none`.
- Scorer SHA-256: `dea3134fbe1e699054daffeee06c077fec8257c0e78dee58ac46d19623e1635f`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 31/60 | 45/60 |
| Success@3 | 42/60 | 45/60 |
| Coverage | 70/120 | 63/120 |
| Incorrect answered | 14/56 | 10/55 |
| False answers | 14/60 | 8/60 |

## Split-specific quality

| Split | Metric | main | retrieval-v2 |
| --- | --- | ---: | ---: |
| dev | Success@1 | 18/30 | 30/30 |
| dev | Success@3 | 23/30 | 30/30 |
| dev | False answers | 1/30 | 0/30 |
| holdout | Success@1 | 13/30 | 15/30 |
| holdout | Success@3 | 19/30 | 15/30 |
| holdout | False answers | 13/30 | 8/30 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 12/18 | 13/18 | 13/18 | 13/18 | 0/12 | 0/12 |
| linux | 11/18 | 14/18 | 18/18 | 14/18 | 4/12 | 4/12 |
| osx | 5/12 | 11/12 | 6/12 | 11/12 | 3/18 | 1/18 |
| windows | 3/12 | 7/12 | 5/12 | 7/12 | 7/18 | 3/18 |

## Scenario-family breakdown

| Family | main Success@1 | retrieval-v2 Success@1 | gain | main incorrect | retrieval-v2 incorrect |
| --- | ---: | ---: | ---: | ---: | ---: |
| arch-package-install | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| audio-proof-export | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| batch-line-counting | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| built-in-zip-creation | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| clipboard-command-output | 0/1 | 1/1 | 1.0000 | 1/1 | 0/1 |
| clipboard-filter-pipeline | 0/1 | 1/1 | 1.0000 | 1/1 | 0/1 |
| clipboard-history-recovery | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| compressed-backup-creation | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| configuration-diff-review | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| cross-volume-archive-move | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| deduplicated-import-queue | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| default-app-association | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| design-review-open | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| desktop-app-log-follow | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-common-file-content | 4/5 | 5/5 | 0.2000 | 0/5 | 0/5 |
| dev39-common-file-copy | 5/5 | 5/5 | 0.0000 | 0/5 | 0/5 |
| dev39-common-unsupported-file-encryption | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-linux-firewall-unsupported | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-linux-interface-address | 3/5 | 5/5 | 0.4000 | 0/5 | 0/5 |
| dev39-linux-systemd-restart | 4/5 | 5/5 | 0.2000 | 0/5 | 0/5 |
| dev39-osx-clipboard-output | 1/5 | 5/5 | 0.8000 | 4/5 | 0/5 |
| dev39-osx-unsupported-dns | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-osx-unsupported-exif | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-windows-file-copy-single | 1/5 | 5/5 | 0.8000 | 3/5 | 0/5 |
| dev39-windows-unsupported-event-log | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| dev39-windows-unsupported-registry | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| directory-link-creation | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| directory-space-breakdown | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| display-brightness-control | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| encrypted-image-mount | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| finder-handoff | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| firewall-rule-change | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| fresh-package-index | 0/1 | 0/1 | 0.0000 | 0/1 | 1/1 |
| growing-log-tail | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| hidden-folder-inventory | 0/1 | 0/1 | 0.0000 | 0/1 | 1/1 |
| https-file-download | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| incident-bundle-assembly | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| incoming-batch-copy | 0/1 | 0/1 | 0.0000 | 1/1 | 1/1 |
| integrity-digest-generation | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| interface-address-provisioning | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| kernel-ring-buffer-review | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| line-oriented-escalation | 0/1 | 1/1 | 1.0000 | 1/1 | 0/1 |
| live-cpu-investigation | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| lossless-video-trim | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| manifest-inspection | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| memory-snapshot | 0/1 | 0/1 | 0.0000 | 0/1 | 1/1 |
| metadata-preserving-archive | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| migration-stream-normalization | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| mount-capacity-triage | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| network-configuration-report | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| ownership-repair | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| package-change-review | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| permission-hardening | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| powershell-alias-documentation | 1/1 | 0/1 | -1.0000 | 0/1 | 1/1 |
| powershell-file-scope | 0/1 | 0/1 | 0.0000 | 1/1 | 1/1 |
| process-inventory | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| process-termination | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| recursive-text-investigation | 0/1 | 0/1 | 0.0000 | 1/1 | 1/1 |
| repository-extension-inventory | 0/1 | 0/1 | 0.0000 | 1/1 | 0/0 |
| route-table-audit | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| screen-region-capture | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| service-health-check | 0/1 | 0/1 | 0.0000 | 0/1 | 1/1 |
| service-log-isolation | 0/1 | 0/1 | 0.0000 | 0/1 | 1/1 |
| shared-drop-review | 0/1 | 0/1 | 0.0000 | 0/0 | 0/0 |
| socket-owner-investigation | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| structured-response-projection | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| template-tree-staging | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| text-file-comparison | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| text-only-content-audit | 1/1 | 1/1 | 0.0000 | 0/1 | 0/1 |
| tree-mirroring | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| wireless-network-join | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| workspace-content-locator | 0/1 | 0/1 | 0.0000 | 0/1 | 1/1 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 86.687 ms | 90.469 ms | 236,061,440 B | 282,919,656 B |
| holdout fresh | 93.736 ms | 94.752 ms | 237,634,232 B | 237,535,928 B |
| warmed query | 93.347 ms | 90.551 ms | 238,306,000 B | 237,421,264 B |

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
- `fresh-2026-09-26-common-positive-01` (manifest-inspection/common), displayed IDs: `none`.
- `fresh-2026-09-26-common-positive-02` (incident-bundle-assembly/common), displayed IDs: `none`.
### candidate
- `fresh-2026-09-26-common-positive-01` (manifest-inspection/common), displayed IDs: `none`.
- `fresh-2026-09-26-common-positive-02` (incident-bundle-assembly/common), displayed IDs: `none`.
- `fresh-2026-09-26-common-positive-04` (shared-drop-review/common), displayed IDs: `none`.
- `fresh-2026-09-26-common-positive-05` (repository-extension-inventory/common), displayed IDs: `none`.
- `fresh-2026-09-26-common-positive-07` (migration-stream-normalization/common), displayed IDs: `none`.
- `fresh-2026-09-26-linux-positive-01` (fresh-package-index/linux), displayed IDs: `example-e1d50ec8bcbdbb1cde2d2d97c841c00ee709fc61c9e125b61d5e6e1cea601d16`.
- `fresh-2026-09-26-linux-positive-04` (memory-snapshot/linux), displayed IDs: `example-0fd79d14a79a448576568d86bd405f2ab60ffc545fe5f9e48956a2fa7f240b13`.
- `fresh-2026-09-26-linux-positive-07` (service-log-isolation/linux), displayed IDs: `example-e749fca6b213fe21f43536cc5a1d83dc0397c5604015dc9f393bd2086dbcae84, example-64d2bca80b945d449e02a015e46da78ddbc1c31ae96c7aecd521b73a199b5ec6`.
- `fresh-2026-09-26-linux-positive-08` (service-health-check/linux), displayed IDs: `example-64d2bca80b945d449e02a015e46da78ddbc1c31ae96c7aecd521b73a199b5ec6, example-1701ba64bdde6b5279e26c70c9d8a21f4f44ae584c2ec202143006693cf82b52`.
- `fresh-2026-09-26-osx-positive-01` (workspace-content-locator/osx), displayed IDs: `example-453abcea6ea8baded3debf3c7dc4ded44ee04405706cd1c95f4eb11faaab182c`.

## Paired bootstrap

- Observed Success@1 gain: `0.2333`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `0.1333`.
- 95% interval: `0.1167` to `0.3500`.

## Independent holdout check

- Holdout Success@1 gain: `0.0667`.
- One-sided 95% lower bound: `-0.0333`.
- Independent holdout decision: **inconclusive**.

## Gate conditions

- Success@1 regressed in: powershell-alias-documentation
- success_at_3 regressed on platform linux
- incorrect_answered_tasks regressed on platform linux
- independent holdout success_at_3 regressed overall
- independent holdout incorrect_answered_tasks regressed overall
- independent holdout success_at_3 regressed on platform linux
- independent holdout incorrect_answered_tasks regressed on platform linux
- independent holdout success_at_3 regressed on platform windows
- independent holdout incorrect_answered_tasks regressed on platform windows
- independent holdout paired bootstrap one-sided 95% lower bound is not above zero

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
