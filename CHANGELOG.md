# Changelog

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
