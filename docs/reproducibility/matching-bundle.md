# Matching bundle

Issue #29 packages the source-backed corpus, lexical index, dense index, and
pinned embedding assets as one offline bundle. The bundle contains all four
platform page sets: `common`, `linux`, `osx`, and `windows`. Platform filtering
remains a query-time policy.

Provision the tldr snapshot and pinned model cache first. Then build offline:

```sh
cargo run --locked --offline --features dev --bin tldr_subset -- \
  bundle-build \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --snapshot tests/fixtures/tldr-full-corpus \
  --model-cache "$RUN_DIR/data/models" \
  --output /tmp/askman-matching-bundle \
  --cli-compatibility 'askman=0.3.3'
```

The output contains:

- `manifest.json`: deterministic bundle identity, source revision/digest,
  parser and component versions, platform policy, CLI compatibility, sizes,
  and SHA-256 digests;
- `matching.db`: source-backed pages and examples, SQLite FTS5 lexical index,
  and sqlite-vec dense index;
- `model-cache/`: the pinned model reference and required model files.

Validate the complete unit without network access:

```sh
cargo run --locked --offline --features dev --bin tldr_subset -- \
  bundle-validate --bundle /tmp/askman-matching-bundle

cargo run --locked --offline --features dev --bin tldr_subset -- \
  query --artifact /tmp/askman-matching-bundle/matching.db \
  --platform linux --query 'search patterns files'
```

Builds use a temporary sibling directory and publish only after corpus,
lexical, dense, model, digest, compatibility, and four-platform checks pass.
Malformed or interrupted builds are removed without replacing an existing
usable bundle. Existing page/example IDs, command syntax, source references,
original content, and platform metadata are retained from the corpus builder.

This ticket does not implement bundle update, release publishing, or shipping
CLI integration.
