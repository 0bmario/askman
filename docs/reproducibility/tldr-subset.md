# Reproducible tldr subset

`manifest.json` declares the pinned source metadata and every selected page.
The builder verifies the manifest's SHA256 over the selected files, parses the
supported `pages/{common,linux,osx,windows}/*.md` shape, records every selected
file as `parsed`, and fails before publication for missing, malformed,
unsupported, broken, or cyclic selected input.

Retrieval selects one page per name for the requested platform: the target OS
page wins, otherwise the common page is used. Other OS variants are excluded.
Alias, moved-page, and disambiguation navigation examples are retained as
source records but never indexed as operational answers.

Use a provisioned local snapshot; this command never accesses the network:

```sh
cargo run --locked --offline --features dev --bin tldr_subset -- \
  build \
  --manifest tests/fixtures/tldr-subset/manifest.json \
  --snapshot tests/fixtures/tldr-subset \
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
records the source attribution and MIT content license. Replace the fixture
with a provisioned snapshot only after updating the manifest digest; no
automatic setup or full-corpus support is provided by this runner.
