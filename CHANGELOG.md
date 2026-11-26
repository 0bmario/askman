# Changelog

## [0.3.11] - 2026-11-26

### Changed
- Queries are faster: askman reads its database through a memory map and loads the tokenizer while the model loads. A query takes about 46-49 ms instead of 59-63 ms (median, three runs against 0.3.10 on an M2 Pro Mac). Answers are unchanged.
- Upgrading from 0.3.10 downloads nothing and uses no more disk.

## [0.3.10] - 2026-11-26

### Changed
- askman no longer ranks pages by how a command's name is spelled. Short names like `df` or `bfs` used to get a boost and hyphenated pages like `ssh-keygen` a penalty, so `--windows show disk partitions` answered `df`; it now answers `diskpart`.
- Some requests now get a different first answer that is less direct: on macOS `ssh into a server` shows `mosh` first, `install a python package` shows `pypy`, and `extract audio from a video` shows `yt-dlp` instead of `ffmpeg`.
- On the askman evaluation set, top-1 rises from 81 to 90 of 150 dev queries and from 36 to 39 of 55 held-back queries. Query time and download size are unchanged.
- Upgrading from 0.3.9 downloads nothing: the database is the same.

## [0.3.9] - 2026-11-26

### Changed
- Queries are faster: askman loads its model about 15 ms quicker. A query takes about 56-58 ms instead of 71-74 ms (median, measured on an M2 Pro Mac). Answers are unchanged.
- Upgrading from 0.3.8 downloads nothing. The first query after upgrading takes slightly longer once (about 92 ms), because askman writes an optimized copy of the model to the data directory. That copy uses about 23 MB of disk. `askman --clean` still removes everything.

## [0.3.8] - 2026-11-25

### Changed
- New commands database (db-v2). `--osx flush dns` now answers `dscacheutil`, and `--windows view the event log` answers `wevtutil`. `spectacle` and `resolvconf` no longer appear for macOS and Windows queries.
- On the askman evaluation set, dev top-1 rises from 37/70 to 39/70 and wrong-platform answers drop from 3 to 1. Query time and download size are unchanged.
- Existing installs download the new database once (59.8 MB). The old `commands.db` stays in the data directory. To remove it, run `askman --clean`: it deletes the whole data directory, so the next query downloads the current database and model again.

### Fixed
- askman exits quietly when its output is closed early, for example `askman ... | head` (#65).

## [0.3.7] - 2026-11-24

### Changed
- Pages for the target platform (`--osx`, `--windows`, `--linux`, or the host default) now rank above near-tied cross-platform pages. For example, `--windows kill a process` returns `taskkill` instead of `fkill`, and `--windows clear dns cache` returns `ipconfig` instead of `resolvconf`.
- Removed the boost for pages that link to GNU, kernel.org and similar man-page sites. It applied mostly to Linux pages, so it pushed Linux answers onto macOS and Windows queries.
- On the askman evaluation set, dev top-1 rises from 32/70 to 37/70 and wrong-platform answers drop from 8 to 3. Query time and download size are unchanged.

## [0.3.6] - 2026-11-24

### Changed
- Queries are embedded with the int8-quantized AllMiniLM-L6-v2 model. First run downloads 23 MB instead of 90 MB, and a query takes about 20 ms less (p95 83-86 ms vs 103-111 ms on an M2 Pro). Aggregate scores on the askman evaluation set are unchanged (dev top-1 32/70, top-3 53/70); a few individual answers change, for example `ssh into a server` now returns `ssh`.
- Existing installs download the new model once. The old model stays in the data directory's `models/` folder; `askman --clean` removes it.

## [0.3.5] - 2026-11-23

### Fixed
- The prebuilt Linux x86_64 binary runs on Ubuntu 22.04+ and Debian 12 again. 0.3.4 was built on a newer runner and required glibc 2.43.
- Releases attach `commands.db` again, so askman 0.3.3 installs keep downloading it.

## [0.3.4] - 2026-11-23

### Added
- Published on crates.io: `cargo install askman`.
- macOS media requests (`say`, `screencapture`) that no source example covers now return no answer instead of a wrong command.

### Changed
- The commands database downloads from the pinned `db-v1` release and is verified by SHA-256, instead of following the latest app release.
