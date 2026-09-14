# Reproducible tldr subset

`manifest.json` declares the pinned source metadata and every selected page.
The builder verifies the manifest's SHA256 over the selected files, parses only
the supported ordinary `pages/{common,linux,osx,windows}/*.md` shape, records
each file as `parsed`, and fails before publication for missing, malformed or
unsupported selected input.

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
  --query 'copy a file to another location'
```

Query output is JSON. Each result includes the exact original command and
example description, deterministic example/page IDs, source path and
revision, platform, language, page/example positions, and a source reference.
The artifact stores original page/example content in source tables and the
derived keyword text in a separate FTS5 table.

The committed fixture is a small English `tldr-pages` snapshot. Its manifest
records the source attribution and MIT content license. Replace the fixture
with a provisioned snapshot only after updating the manifest digest; no
automatic setup or full-corpus support is provided by this runner.
