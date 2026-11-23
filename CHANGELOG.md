# Changelog

## [0.3.4] - 2026-11-23

### Added
- Published on crates.io: `cargo install askman`.
- macOS media requests (`say`, `screencapture`) that no source example covers now return no answer instead of a wrong command.

### Changed
- The commands database downloads from the pinned `db-v1` release and is verified by SHA-256, instead of following the latest app release.
