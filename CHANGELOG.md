# Changelog

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
