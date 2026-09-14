# Full-corpus build record

Issue #16 uses a declared, provisioned corpus selection. The selection is
English and follows the importer directories `common`, `linux`, `osx`, and
`windows`; it does not imply that released binaries contain four-platform
support.

Build offline from the committed fixture:

```sh
cargo run --locked --offline --features dev --bin tldr_subset -- \
  build \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --snapshot tests/fixtures/tldr-full-corpus \
  --output /tmp/askman-full-corpus.db

cargo run --locked --offline --features dev --bin tldr_subset -- \
  query --artifact /tmp/askman-full-corpus.db \
  --platform linux --query 'search patterns files'

cargo run --locked --offline --features dev --bin tldr_subset -- \
  inspect --artifact /tmp/askman-full-corpus.db \
  --platform common --page vi
```

The manifest lists every selected page. Excluded pages remain in that list and
must have a non-empty reason in `exclusions`; exclusions are never inferred
from parser failures. The artifact preserves page IDs, source paths, source
revision, source references, original content, and example IDs so later vector
fields can be added without losing provenance.

The lexical recipe is recorded in both manifest and artifact: SQLite FTS5
`unicode61`, fields `page.command`, `page.description`,
`example.description`, and `example.command`; queries split on non-alphanumeric
characters except `_`, lowercase ASCII, quote tokens, sort/deduplicate, and
AND-join them.

The fixture attributes content to `tldr-pages` under its MIT license. A real
provisioned corpus must replace the fixture manifest revision, selection,
exclusions, and digest together; tests do not fetch the network.
