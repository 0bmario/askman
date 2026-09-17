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

`--cli-compatibility` must use `askman=<version>` with no whitespace. The
builder requires the manifest selection, including excluded files, to cover
every `.md` page below `pages/common`, `pages/linux`, `pages/osx`, and
`pages/windows` in the pinned snapshot.

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
The output path must be new; an existing file or directory is refused. This
keeps a usable bundle intact if construction is malformed or interrupted.
Existing page/example IDs, command syntax, source references, original
content, and platform metadata are retained from the corpus builder.

## Runtime lifecycle

The shipping CLI consumes only the active validated bundle. First-use setup and
explicit update fetch these fixed assets from the compatible release tag (the
current CLI version, never a `latest` endpoint):

- `matching-bundle-manifest.json`
- `matching-bundle.tar.gz`

The archive is unpacked into a private staging directory. The embedded manifest
must exactly match the release manifest, and `bundle-validate`'s same
`validate_matching_bundle` path verifies every component version, size,
SHA-256 digest, source identity, four-platform database coverage, and pinned
model asset before publication.

Validated bundles are stored below the Askman data directory at
`bundles/<immutable-bundle-id>`. Existing IDs are never replaced. The active
state is written to a temporary file and atomically replaced only after the
complete record is synced; an interrupted write leaves the previous selection
active. A successful update records the former active ID as the rollback
target. Failed downloads, extraction, validation, or activation leave that
state and bundle untouched.

Use the explicit lifecycle commands:

```sh
askman setup
askman update
askman rollback
```

Normal queries only read the active state and local bundle. If setup has not
completed, the query exits non-zero with an actionable setup error; it never
silently downloads, rebuilds, deletes, or mixes assets.
