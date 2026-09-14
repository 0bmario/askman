# Held-out retrieval evidence

Issue #20 records one frozen comparison of the keyword baseline and the
selected hybrid candidate from issue #19. It is local engineering evidence;
it does not change the shipping CLI, database, model, release, server, or
command-execution behavior.

## Frozen protocol

The protocol is
`tests/fixtures/evaluation/heldout-evidence-config-v1.json`.

- Dataset: `askman-evaluation-v1`, holdout split, 30 tasks.
- Holdout SHA256: `ddd20209e2426afe6b3122ab43b953822e8a1c2e70b147045930558345bee320`.
- Evidence config SHA256: recorded and enforced by the runner.
- Quality runs: one keyword evaluation and one hybrid evaluation.
- Hybrid: `rrf-k60-b8-cutoff-0.50` from the committed frozen config; no candidate
  flag or holdout tuning is accepted by this runner.
- Workload: all 30 holdout questions in dataset order.
- Performance: five fresh evidence-runner/helper process pairs, two discarded
  warm-up queries per pair, then 30 measured queries per pair; one additional
  process with two warm-up queries and 30 measured in-process queries.
- Performance query scope: selected hybrid end-to-end, including FTS5, the
  dense helper boundary, RRF fusion, and the weak-match cutoff.
- Threading: default process parallelism; the report records overrides and
  notes that effective ONNX Runtime threads are not instrumented.
- Power: host state is recorded when available; power settings are not changed.
- Provider: CPU only; no GPU.

The evaluator reports Success@1/3, candidate recall, coverage, incorrect
answered among answered answerable tasks, and false answers on unanswerable
tasks. Every value is a `count` and `denominator`.

## Reproduce

Run setup/download separately while online. The evidence command then builds
the local fixture and runs the evaluator and helper with networking denied:

```sh
cargo fetch --locked
RUN_DIR="$(mktemp -d)"
scripts/smoke_offline.sh provision "$RUN_DIR"
scripts/smoke_offline.sh evidence "$RUN_DIR"
```

`provision` is the only networked step. `evidence` uses the existing
`sandbox-exec` policy `(deny network*)` for artifact builds, evaluator
subprocesses, model initialization, and queries. It writes
`$RUN_DIR/heldout-evidence.json`, plus lexical and dense build metadata. The
JSON is the machine-readable result and includes input/config digests,
database size, build times, host/resource data, per-task results, and
representative successes and abstentions.

For a direct invocation against already provisioned assets, use:

```sh
python3 scripts/run_heldout_evidence.py \
  --artifact "$RUN_DIR/heldout-dense.db" \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-holdout-v1.json \
  --hybrid-config tests/fixtures/evaluation/hybrid-config-v1.json \
  --evidence-config tests/fixtures/evaluation/heldout-evidence-config-v1.json \
  --dense-helper "$RUN_DIR/target/debug/tldr_subset" \
  --model-cache "$RUN_DIR/data/models" \
  --build-metadata "$RUN_DIR/lexical-build.txt" \
  --dense-build-metadata "$RUN_DIR/dense-build.txt" \
  --network-probe "$RUN_DIR/evidence-network-probe.txt" \
  --output "$RUN_DIR/heldout-evidence.json"
```

This direct form does not install assets or enforce a network policy; it
consumes a previously recorded probe. Use the offline smoke entrypoint for the
provisioned-query claim.

## Recorded result

The run was on an Apple M2 Pro, 10 logical CPUs, 16 GiB RAM, macOS 26.6.2,
with Rust 1.88.0, `fastembed 4.8.0`, `sqlite-vec 0.1.6`, and ONNX Runtime
1.20.0.

| Retriever | Success@1 | Success@3 | Candidate recall | Coverage | Incorrect answered | False unanswerable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| keyword | 10/10 | 10/10 | 10/10 | 10/30 | 0/10 | 0/20 |
| frozen hybrid | 10/10 | 10/10 | 10/10 | 10/30 | 0/10 | 0/20 |

Build time was 9 ms for the lexical artifact and 12 ms for the dense index;
database sizes were 77,824 and 1,720,320 bytes respectively. The five
fresh-process runs measured initialization p50/p95 of 3,493.542/3,620.066 ms,
model load p50/p95 of 3,485/3,611 ms, end-to-end query p50/p95 of 2.879/6.625
ms, and maximum reported peak memory of 345,473,024 bytes. The one warmed
process measured end-to-end query p50/p95 of 2.770/5.148 ms and 345,358,336
bytes peak memory.
The network probe passed under the deny policy.

The report retains exact digests and per-task data; the table above is only the
human-readable summary. Representative successful queries and correct
abstentions are in the JSON artifact. No incorrect or false answers were
observed, so there is no observed failure example to fabricate.

## Deterministic invariants

The report checks and records:

- platform selection is target platform first, then `common`;
- page/example IDs and source paths/refs/revisions are source-backed and
  unique;
- reference pages resolve to operational destinations, with no reference
  replacing an example in retrieval output.

The artifact builder and evaluator validate these identities before scoring.

## Interpretation and limits

The holdout contains 10 answerable and 20 unanswerable tasks. Thus the
answerable metrics have denominator 10, false-answer metrics denominator 20,
and coverage denominator 30. The report retains these small denominators;
percentages would imply more precision than this fixture supports. Fresh-process
p95 has five observations and warm p95 is one 30-query workload, so these are
machine-specific engineering measurements, not capacity guarantees.

The checked-in JSON artifact records one named-host run. Reruns remain local;
their host, paths, timings, and working-tree digest are machine-specific. No
holdout tuning or re-run was performed after observing results; the
reproducible command above is the source of the result.

The recommendation is **insufficient evidence** unless a future, explicitly
reviewed dataset changes that conclusion. This fixture cannot support claims
of superiority, production quality, or adoption.

Milestone-2 remaining work is deliberately outside this issue: CLI
integration, automatic matching-asset setup, explicit updates, and packaging
investigation.
