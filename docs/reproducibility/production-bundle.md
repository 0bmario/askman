# Askman 0.4.0 matching-bundle evidence

> The checked-in evidence below is dev-only. It was generated with
> `--allow-dirty`; the report records `git_dirty=true` and
> `production_eligible=false`. Do not promote this run. Re-run from a clean
> Darwin/arm64 tree without `--allow-dirty` for production evidence.

The production corpus is a frozen English snapshot of `tldr-pages` at commit
`e7186598dc466e69c2adf5d8f06037d5b186f08d`. The immutable source URL is
`https://github.com/tldr-pages/tldr/tree/e7186598dc466e69c2adf5d8f06037d5b186f08d`.
The GitHub archive is verified before extraction:

```text
archive SHA256  95f4f2604f407d8e148a67be88c9b8957f7ea4da344b6754cbfdb072f94057dd
LICENSE.md SHA256 826498c9793c53709035760c33bd6681e48380d34031320447febe675420ef4d
manifest SHA256 7915b2e6aa0b9006225b8966f97655c7c82507fcf9bfffcc1f314ab41a4fdde2
exclusions SHA256 e6c349034ffb255a132a1bc94ed412a0b7a9b29a0b31d67eeb906f9590628ac9
```

The committed [manifest](artifacts/tldr-pages-e7186598-manifest.json) accounts
for every `.md` file below `pages/common`, `pages/linux`, `pages/osx`, and
`pages/windows`. It contains 7,415 source files: 7,358 parsed pages and 57
explicit parser/reference exclusions. Exclusions remain in `source_files` with
their source SHA256, byte length, status, and reason; excluded source bytes are
not embedded in the SQLite artifact. No page is silently dropped.

Provision and build with the networked source step isolated from the offline
builder. The production command must use a clean tree and omit
`--allow-dirty`:

```sh
python scripts/provision_tldr_bundle.py \
  --work-dir "$RUN_DIR" \
  --model-cache "$RUN_DIR/data/models" \
  --output "$RUN_DIR/matching-bundle" \
  --archive-output "$RUN_DIR/matching-bundle.tar.gz" \
  --tldr-subset target/debug/tldr_subset \
  --askman-candidate target/debug/askman_candidate \
  --runtime-lib "$RUN_DIR/onnxruntime/onnxruntime-osx-arm64-1.20.0/lib" \
  --runtime-archive "$RUN_DIR/onnxruntime-osx-arm64-1.20.0.tgz" \
  --detached-manifest-output "$RUN_DIR/matching-bundle-manifest.json" \
  --check-rebuild
```

For local development evidence only, append `--allow-dirty`. The resulting
report is explicitly production-ineligible.

The model is `Qdrant/all-MiniLM-L6-v2-onnx` revision
`5f1b8cd78bc4fb444dd171e59b18f3a3af89a079`, using `fastembed-4.8.0` and the
provisioned ONNX Runtime `1.20.0` (archive SHA256
`2bcfaafa9ff0a3a94f78e3af2f135ffde5bb2d79b08e83a50dbc450b0d20ddae`; macOS
library SHA256
`d8be733cb8dd097cfe2b21e069a7462b5ff561625141d9c4b98d866f15bfb852`). The builder creates and validates
`matching-bundle-v2` with CLI compatibility `askman=0.4.0`, then probes all
four target-platform policies offline. Its dense component is
`dense-vec0-v2` / `partitioned-knn-v1`: vec0 is partitioned by `platform`,
stores a stable `example_dense.dense_rowid-v1` mapping, queries target and
`common` partitions separately with `k <= 4096`, and uses SQL
`vec_distance_cosine` only when the partition union cannot fill the requested
unique-page budget. It requires the host's verified ONNX Runtime 1.20.0
library and emits a byte-identical detached `matching-bundle-manifest.json`
release asset. Existing output paths are refused.
The Cargo package and the bundle now share the `0.4.0` compatibility value;
the candidate and release binaries validate that value from their compiled
package version.
The exact pinned model README/license notice is vendored at
`artifacts/model-README-5f1b8cd78bc4fb444dd171e59b18f3a3af89a079.md` and has
SHA256 `2c47a70b94fe29e24841acf0e177949f1c9aa543e450d43af7e872ea81e43501`.
Production bundle-builds are canonicalized to Darwin/arm64 and require both
`tldr_subset` and `askman_candidate` to pass the same `otool` architecture and
exact `@rpath` linkage checks against the verified ORT dylib path and SHA256.

The dev evidence build (two independent builds plus deterministic archive
rebuild) at this source and model pin produced:

```text
bundle_id       matching-bundle-v2:8ab84c666b7420575f0df86fd174465d1be8810d15d6ecf0465414213ea7d84b
source digest   5337158d01155689c62d3ba2fa33a2d04fd2904b35e9088c54d041a562a08905
examples        32173
matching.db     166973440 bytes
matching.db SHA 3bcc830af2e289b4f02d45d271657a10b51a2b7eca20830ab4b87b2aac15a9d6
bundle tree SHA bd3caf37f2898a71daa698eff931644680a934b98d591188be76286ad991e83c
bundle.tar.gz SHA bc663019097671dda61a8d35f010aa055cb035959a9eaad6c2d2952732817cc1
manifest SHA    3af378161c69dc7d8604dcd22d24fd6c5d0f149411c42e9d8602153d3014174b
detached SHA    3af378161c69dc7d8604dcd22d24fd6c5d0f149411c42e9d8602153d3014174b
notice tldr SHA 5e2b471626a0cd4881d0d6be277d45fd2e7d131351638013e0204b38d8fa7f64
notice model SHA 2c47a70b94fe29e24841acf0e177949f1c9aa543e450d43af7e872ea81e43501
```

`--check-rebuild` builds a second fresh bundle and compares logical tree,
manifest, and database hashes. The observed rebuild matched exactly. The
report also records the dirty-tree marker, git status/diff/tree hashes,
builder binary hashes, toolchain, and platform. It records source/archive/model
identities, inventory, probe results, component hashes, and the rebuild result.
The recorded run is
[available as JSON](artifacts/tldr-pages-e7186598-bundle-provision.json); it is
dev evidence, not a production release asset or replacement for the frozen
manifest.

The single-process offline dense-server benchmark against this rebuilt DB is
recorded in
[dense-strategy-benchmark-v1.json](artifacts/dense-strategy-benchmark-v1.json).
Four representative target/common and host-default queries returned eight
results in 193–281 ms after model startup; the focused regression suite also
proves the >4096-vector underfill path uses SQLite cosine distance and matches
the vec0 f32 norm semantics.
