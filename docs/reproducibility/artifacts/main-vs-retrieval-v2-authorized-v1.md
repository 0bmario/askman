# Askman release gate

Decision: **better_askman**

## Inputs and builds

- Generated: `2026-09-26T12:17:37.677130+00:00`
- Evidence scope: `release-gate`
- Query network policy: `macOS sandbox-exec deny network*`
- Reproduction: `scripts/run_release_gate.py --candidate-working-tree --main-data-dir /tmp/askman-goal.Fk5Zkh/main-import-home/Library/Application Support/askman --bundle /tmp/askman-goal.Fk5Zkh/bundle-final-v2 --allow-holdout --output-json /tmp/askman-goal.Fk5Zkh/release-gate-authorized-v1.json --output-markdown /tmp/askman-goal.Fk5Zkh/release-gate-authorized-v1.md`
- Freeze: `evaluation-v2-release-benchmark-v3`
- Main commit: `8bd9fa296ea7e2f461202091f2ade47221bc8a0e`
- Main Cargo.lock SHA-256: `79ee86b480ce00437f814657327b326b725ecd13965d1e958772b5d0ff415990`
- Main binary SHA-256: `e24f91a02008c7e9c6807d4d62c7d8b07170c61197f588e7ab3edf7513cfe38d`
- Candidate commit: `f61e3afa83e2bb6171c702f2bf8107ad40e6c267`
- Candidate Cargo.lock SHA-256: `c7eb0288a893ce1f387118cb0fc7370465d2efdfe33de1518ec2715b81c94f76`
- Candidate binary SHA-256: `bf3e293d6ecfee8f5d0bbbaafaac57b7498a8fc92adcb8865120b89ff6a077d9`
- Freeze manifest SHA-256: `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Gate runner SHA-256: `55c0cd82d96507b95d68a7ac8705c0d35011a6202bfde2fa1a4a2457837458cb`
- Candidate bundle: `matching-bundle-v2:8e53794515abdcaa0e304fb3ea533144461ae7018f87264c2fabcbd3fee191e4`
- Candidate bundle tree SHA-256: `082553b9446a6bf75aa0cdd2506ff283fbd1dc36ec40fc8333789fd17c74bfbf`
- Main data tree SHA-256: `8dbd6badbb01e78b321608ebfb425b70eec1d7674d41991b3e4913c67b4033f8`
- Main database SHA-256: `ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db` (pinned evaluation baseline match: `True`).
- Shared visible corpus: `142` examples; SHA-256 `e512688f1945ee23d594b856ce857d01e1b063a84bba5821c1889146133c2f0c`.
- Benchmark corpus: `tldr-subset-v3` at `e1cb966e711d73c42d75e79834be7e4dc17264ef`; SHA-256 `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
- Matching model assets verified: `6`.
- Dev dataset SHA-256: `216c0e26f24fda7df197011be4f8add33b6852b7907b32966b0c77e0a26c947d`
- Holdout dataset SHA-256: `1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418`
- Scorer SHA-256: `e99c48c3b0540c0586615bbdb436052af2ab29f20dbc590341fc0aee2ce73a27`
- Per-file input digests: recorded in the machine-readable report.

## User-visible quality

| Metric | main | retrieval-v2 |
| --- | ---: | ---: |
| Success@1 | 37/60 | 49/60 |
| Success@3 | 48/60 | 50/60 |
| Coverage | 65/120 | 62/120 |
| Incorrect answered | 10/58 | 6/56 |
| False answers | 7/60 | 6/60 |

## Platform breakdown

| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 19/20 | 20/20 | 20/20 | 20/20 | 0/10 | 0/10 |
| linux | 8/15 | 11/15 | 11/15 | 11/15 | 5/15 | 5/15 |
| osx | 9/15 | 13/15 | 11/15 | 13/15 | 1/15 | 1/15 |
| windows | 1/10 | 5/10 | 6/10 | 6/10 | 1/20 | 0/20 |

## Scenario-family breakdown

| Family | main Success@1 | retrieval-v2 Success@1 | gain | main incorrect | retrieval-v2 incorrect |
| --- | ---: | ---: | ---: | ---: | ---: |
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
| holdout39-common-file-concatenation | 5/5 | 5/5 | 0.0000 | 0/5 | 0/5 |
| holdout39-common-text-sort-descending | 5/5 | 5/5 | 0.0000 | 0/5 | 0/5 |
| holdout39-common-unsupported-dns | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| holdout39-linux-apt-update | 1/5 | 1/5 | 0.0000 | 2/3 | 0/1 |
| holdout39-linux-unsupported-firewall | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| holdout39-linux-unsupported-pacman | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| holdout39-osx-open-default | 3/5 | 3/5 | 0.0000 | 0/5 | 2/5 |
| holdout39-osx-speech-phrase | 5/5 | 5/5 | 0.0000 | 0/5 | 0/5 |
| holdout39-osx-unsupported-sms | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| holdout39-windows-list-current | 0/5 | 0/5 | 0.0000 | 1/5 | 4/5 |
| holdout39-windows-unsupported-event-log | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |
| holdout39-windows-unsupported-firewall | 0/0 | 0/0 | 0.0000 | 0/0 | 0/0 |

## Performance

| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |
| --- | ---: | ---: | ---: | ---: |
| dev fresh | 88.616 ms | 91.134 ms | 237,683,384 B | 245,007,008 B |
| holdout fresh | 87.515 ms | 87.857 ms | 237,224,632 B | 237,879,992 B |
| warmed query | 91.639 ms | 88.560 ms | 237,175,480 B | 237,535,904 B |

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
- `holdout-v2r1-holdoutlinux-packages-01` (holdout39-linux-apt-update/linux), displayed IDs: `none`.
- `holdout-v2r1-holdoutlinux-packages-02` (holdout39-linux-unsupported-pacman/linux), displayed IDs: `example-e1d50ec8bcbdbb1cde2d2d97c841c00ee709fc61c9e125b61d5e6e1cea601d16, example-abeeeec14691630cd2bbb82659839005eb339a0e35a5c4c36f10ec358cab835d, example-26a75f510d23eade1920023e9d21690e523c6712534627e709bc9c6acf4c41a3, example-5270e7367ac85aacdf86577d153a225237069a6d0d8a97e0eb86ee127154898b, example-bde8009e70f67dba9b35b180a98ad54adb48c31577caf4c4494aa5ba1e09c904, example-7df27974797b25d1a000ca98ed99d766c15023775f7d2f210bce3fa01a661097, example-54f92822e448d5c7c1633ede9176a56d4e1c7354bf9ed2cfb3a9381c2fe14376`.
### candidate
- `holdout-v2r1-holdoutlinux-packages-01` (holdout39-linux-apt-update/linux), displayed IDs: `none`.
- `holdout-v2r1-holdoutlinux-packages-02` (holdout39-linux-unsupported-pacman/linux), displayed IDs: `example-e1d50ec8bcbdbb1cde2d2d97c841c00ee709fc61c9e125b61d5e6e1cea601d16`.
- `holdout-v2r1-holdoutlinux-packages-03` (holdout39-linux-unsupported-pacman/linux), displayed IDs: `example-e1d50ec8bcbdbb1cde2d2d97c841c00ee709fc61c9e125b61d5e6e1cea601d16`.
- `holdout-v2r1-holdoutlinux-packages-04` (holdout39-linux-unsupported-pacman/linux), displayed IDs: `example-e1d50ec8bcbdbb1cde2d2d97c841c00ee709fc61c9e125b61d5e6e1cea601d16`.
- `holdout-v2r1-holdoutlinux-packages-05` (holdout39-linux-unsupported-pacman/linux), displayed IDs: `example-e1d50ec8bcbdbb1cde2d2d97c841c00ee709fc61c9e125b61d5e6e1cea601d16`.
- `holdout-v2r1-holdoutlinux-unsupported-a-02` (holdout39-linux-apt-update/linux), displayed IDs: `none`.
- `holdout-v2r1-holdoutlinux-unsupported-a-03` (holdout39-linux-apt-update/linux), displayed IDs: `none`.
- `holdout-v2r1-holdoutlinux-unsupported-a-04` (holdout39-linux-apt-update/linux), displayed IDs: `none`.
- `holdout-v2r1-holdoutlinux-unsupported-a-05` (holdout39-linux-unsupported-pacman/linux), displayed IDs: `example-e1d50ec8bcbdbb1cde2d2d97c841c00ee709fc61c9e125b61d5e6e1cea601d16`.
- `holdout-v2r1-holdoutosx-navigation-03` (holdout39-osx-open-default/osx), displayed IDs: `example-9331d0a2aff965799fd3340d9f276dfb2242f1901c04cdbd2720aa32fd83839c`.

## Paired bootstrap

- Observed Success@1 gain: `0.2000`.
- 10,000 resamples; seed `33031`.
- One-sided 95% lower bound: `0.1167`.
- 95% interval: `0.1000` to `0.3000`.

## Gate conditions

- All ADR-0001 conditions passed.

## Limitations

- The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.
- Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.
- Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.
- Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.
