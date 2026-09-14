# Reproducible tldr corpus artifacts

The `tldr_subset` runner builds a source-backed SQLite artifact from a
provisioned local snapshot. A v3 manifest records the pinned English source,
revision, complete file selection, lexical-index recipe, and any explicit
exclusions. The digest covers every selected file, including excluded files.

Every selected file is recorded as `parsed` or `excluded` with its SHA256 and
byte length. A selected file that is missing, malformed, unsupported, or not
UTF-8 fails the build unless it is explicitly listed in `exclusions` with a
reason. Unresolved and cyclic page references always block promotion.

The builder writes a temporary SQLite file, checks SQLite integrity, source and
page identities, reference resolution, lexical rows, and row accounting, then
atomically renames the validated file over the requested output. A failed or
interrupted build removes only its temporary file and leaves the prior output
usable.

Retrieval selects one page per name for the requested platform: the target OS
page wins, otherwise the common page is used. Other OS variants are excluded.
Alias, moved-page, and disambiguation navigation examples are retained as
source records but never indexed as operational answers.

Use a provisioned local snapshot; this command never accesses the network:

```sh
cargo run --locked --offline --features dev --bin tldr_subset -- \
  build \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --snapshot tests/fixtures/tldr-full-corpus \
  --output /tmp/askman-tldr-subset.db

cargo run --locked --offline --features dev --bin tldr_subset -- \
  query \
  --artifact /tmp/askman-tldr-subset.db \
  --platform linux \
  --query 'copy a file to another location'

cargo run --locked --offline --features dev --bin tldr_subset -- \
  inspect \
  --artifact /tmp/askman-tldr-subset.db \
  --platform common \
  --page cp
```

Query output is JSON. Each result includes the exact original command and
example description, deterministic example/page IDs, source path and
revision, platform, language, page/example positions, and a source reference.
The artifact stores original page/example content in source tables and the
derived keyword text in a separate FTS5 table. Search returns at most one best
example per selected page. `inspect` returns the selected full page; aliases
and moved pages return their destination, while disambiguation pages return
all destinations.

The committed fixture is a small English `tldr-pages` snapshot. Its manifest
records the source attribution and MIT content license. The full-corpus fixture
exercises all four importer directories (`common`, `linux`, `osx`, `windows`)
and an explicit exclusion; it is intentionally small for offline tests.

The build command prints build time, peak resident memory when the host exposes
it, artifact size, hardware label, exclusion count, and source digest. Set
`ASKMAN_BUILD_HARDWARE` to override the detected label when recording a named
benchmark machine. The four-platform selection follows the existing importer;
this does not provide four-platform binary-release support or change release
automation.

For the committed fixture on `Mac14,9 (macOS aarch64)`, one local run recorded:

```text
build_time_ms=8
peak_memory_bytes=15712256
artifact_size_bytes=77824
excluded_files=1
source_digest=5cefff74aec82018bd54887666fb1de5c185aa213bc5f2800b26b3441250c36a
```
