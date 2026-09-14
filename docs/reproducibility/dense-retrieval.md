# Dense retrieval candidate

Issue #18 adds a development-only dense candidate beside the validated lexical
artifact. It uses the fixed `Qdrant/all-MiniLM-L6-v2-onnx` model already pinned
by `scripts/smoke_offline.sh`:

- model revision: `5f1b8cd78bc4fb444dd171e59b18f3a3af89a079`
- runtime: `fastembed 4.8.0`, CPU provider
- dimensions: `384`
- tokenizer maximum length: `512`
- output: L2-normalized vectors
- SQLite distance: cosine
- recipes: `description` and `description-plus-parent`

The model cache is verified by reference revision and per-file SHA256 before
loading. The dense artifact records the model, asset hashes, dimensions,
normalization, distance metric, recipe and source digest. It copies the
validated lexical artifact to a temporary replacement, inserts vectors in
batches inside one transaction, validates identity/row coverage/vector shape,
then atomically publishes the output. The lexical input is never modified.

## Build

Provision the model assets while online using the existing fixed-asset harness,
then keep the build/query phase offline:

```sh
RUN_DIR="$(mktemp -d)"
scripts/smoke_offline.sh provision "$RUN_DIR"

# macOS: compile/load against the provisioned ONNX Runtime.
export DENSE_ORT="$RUN_DIR/onnxruntime/onnxruntime-osx-arm64-1.20.0"
export DYLD_LIBRARY_PATH="$DENSE_ORT/lib"
export LIBONNXRUNTIME_NO_PKG_CONFIG=1
export ORT_LIB_LOCATION="$DENSE_ORT"
export ORT_PREFER_DYNAMIC_LINK=1

cargo run --locked --offline --features dev --bin tldr_subset -- \
  build --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --snapshot tests/fixtures/tldr-full-corpus --output /tmp/askman-eval.db

cargo run --locked --offline --features dev --bin tldr_subset -- \
  dense-build --artifact /tmp/askman-eval.db \
  --model-cache "$RUN_DIR/data/models" \
  --output /tmp/askman-dense-description.db \
  --recipe description

cargo run --locked --offline --features dev --bin tldr_subset -- \
  dense-build --artifact /tmp/askman-eval.db \
  --model-cache "$RUN_DIR/data/models" \
  --output /tmp/askman-dense-parent.db \
  --recipe description-plus-parent
```

On macOS, keep the pinned ONNX Runtime from the smoke harness first in
`DYLD_LIBRARY_PATH` (for example,
`$RUN_DIR/onnxruntime/onnxruntime-osx-arm64-1.20.0/lib`); the harness records
the required runtime and hashes. A
missing, wrong-revision or hash-mismatched model fails with an explicit
offline-asset error. The dense path has no keyword fallback.

## Development evaluation

`dense-server` loads one validated dense artifact and serves JSON-lines queries.
The evaluator selects the best vector result for each distinct page, emits at
most three pages, and reports the same task metrics as the keyword and
current-adapter baselines. It also reports model-load/startup time, repeated
query p50/p95 and peak memory.

Run both declared recipes on development tasks only:

```sh
cargo build --locked --offline --features dev --bin tldr_subset

python3 scripts/evaluate_retrieval.py \
  --artifact /tmp/askman-dense-description.db \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-dev-v1.json \
  --split dev --retriever dense \
  --dense-helper target/debug/tldr_subset \
  --model-cache "$RUN_DIR/data/models"

python3 scripts/evaluate_retrieval.py \
  --artifact /tmp/askman-dense-parent.db \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-dev-v1.json \
  --split dev --retriever dense \
  --dense-helper target/debug/tldr_subset \
  --model-cache "$RUN_DIR/data/models"
```

Do not inspect or tune against the holdout file in this ticket. Holdout access
belongs to the later comparison/evidence tickets.

## Provisional development result

Using the pinned model/runtime on the fixture corpus (5 operational examples),
the development comparison was:

| Retriever | Success@1 | Success@3 | Candidate recall | Coverage | False unanswerable |
| --- | ---: | ---: | ---: | ---: | ---: |
| keyword | 13/13 | 13/13 | 13/13 | 13/30 | 0/17 |
| adapted-current | 13/13 | 13/13 | 13/13 | 13/30 | 0/17 |
| dense `description` | 12/13 | 13/13 | 13/13 | 30/30 | 17/17 |
| dense `description-plus-parent` | 12/13 | 13/13 | 13/13 | 30/30 | 17/17 |

Dense `incorrect answered` was `0/13` for both recipes. The dense result has
full coverage because this ticket deliberately evaluates plain vector ranking
without weak-match filtering. The later comparison ticket owns weak-match and
hybrid decisions. This is not a quality claim.

The same-run provisional resource comparison was:

| Retriever/index | Build ms | Build peak memory | Query p50 | Query p95 |
| --- | ---: | ---: | ---: | ---: |
| keyword lexical | 18 | 14.1 MB | 0.032 ms | 0.074 ms |
| adapted-current lexical | 18 | 14.1 MB | 0.034 ms | 0.188 ms |
| dense `description` | 43 | 345.1 MB | 7.330 ms | 12.171 ms |
| dense `description-plus-parent` | 56 | 347.3 MB | 6.493 ms | 10.867 ms |

Dense model startup was 3686 ms / 3664 ms and model load was 3675 ms / 3653 ms
for `description` / `description-plus-parent`; the dense artifact was 1.72 MB
versus 77.8 KB for the lexical artifact. Baseline query timings include the
SQLite lookup and Python projection; dense timings include the JSON-lines helper
boundary and embedding query. Measurements are preliminary and machine-specific
(`macos aarch64`, five operational examples, 30 development tasks).
