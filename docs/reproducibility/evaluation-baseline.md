# Frozen retrieval evaluation

Issue #17 freezes a small, source-backed benchmark before retrieval tuning.
It is preliminary engineering evidence, not user or production validation.

## Frozen inputs

- Dataset: `askman-evaluation-v1`, 60 tasks across two label files.
- Split: `scenario-family-split-v1`, 30 development and 30 holdout tasks.
- Scenarios stay whole: six families per split, five tasks per family.
- Scorer: `task-scorer-v1`.
- Corpus ID: `fixture-tldr-full-corpus-v1:d93ffff3c216b85caabdec2a36c6f20a9107526a32143a7bb2cc086dc77d5822`.
- Manifest SHA256: `68ae06300afdaee1515ef7c6248f35056e871e73d07778f2e1c2f636589c8461`.

The reviewed development labels live in
`tests/fixtures/evaluation/frozen-dev-v1.json`; holdout labels live separately
in `tests/fixtures/evaluation/frozen-holdout-v1.json`, outside the corpus
snapshot. A normal development run reads only the development file. The
separate intent record contains task intent; the split files contain platform,
acceptable example IDs and rationales. Retrieval indexes contain only
source-backed page/example fields. Four
previously inspected audit prompts remain development tasks: `move files to
docs`, `restart systemd`, `find text in compressed logs`, and `make my database
fast without changing anything`.
The authoring and adjudication record is in
`docs/reproducibility/evaluation-authoring.md`.

An answer is successful only when a displayed example ID is acceptable. A
matching command name with unsuitable behavior receives no credit. Empty
acceptable IDs explicitly mark an unanswerable task. Multiple IDs are allowed.

## Run offline

Build the pinned fixture first, then run the controlled baselines:

```sh
cargo run --locked --offline --features dev --bin tldr_subset -- \
  build --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --snapshot tests/fixtures/tldr-full-corpus --output /tmp/askman-eval.db

python3 scripts/evaluate_retrieval.py \
  --artifact /tmp/askman-eval.db \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-dev-v1.json \
  --split dev --retriever keyword

python3 scripts/evaluate_retrieval.py \
  --artifact /tmp/askman-eval.db \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-dev-v1.json \
  --split dev --retriever current-adapter

# Holdout labels are a separate explicit input and require an access flag.
python3 scripts/evaluate_retrieval.py \
  --artifact /tmp/askman-eval.db \
  --manifest tests/fixtures/tldr-full-corpus/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-holdout-v1.json \
  --split holdout --allow-holdout --retriever keyword
```

The default is development-only. Holdout labels require the separate holdout
file plus explicit `--split holdout --allow-holdout`; the output records that
access and its UTC time. The runner rejects a changed artifact or manifest,
missing acceptable IDs, or labels outside the selected platform, with an
explicit migration/invalidation error. Rebuild the dataset labels and
increment the dataset/corpus IDs before accepting changed source artifacts.

`keyword` uses the artifact's declared FTS5 query recipe, platform precedence,
and one result per selected page before displaying three results. The
`current-adapter` is clearly labeled because the released Askman ranker
consumes MiniLM L2 distances. It applies the current Rust command/domain
heuristics to the same deterministic lexical candidate pool and normalized
surrogate distance. It is a controlled adapter, not a claim to reproduce the
historical model output.

The unmodified historical-policy smoke remains separate:
`scripts/smoke_offline.sh`. It must not be mixed into these scores.

## Metrics

Each report contains per-task displayed and candidate example IDs plus counts
and denominators for:

- Success@1 and Success@3 over answerable tasks.
- Candidate recall over answerable tasks, before display ranking.
- Coverage over all tasks: non-empty displayed result.
- Incorrect answered tasks over answered answerable tasks: non-empty but no acceptable ID.
- False answers on unanswerable tasks over unanswerable tasks.

For the committed fixture, the deterministic keyword run currently reports:

```text
dev:     Success@1 13/13, Success@3 13/13, candidate recall 13/13,
         coverage 13/30, incorrect answered 0/13, false unanswerable 0/17
holdout: Success@1 10/10, Success@3 10/10, candidate recall 10/10,
         coverage 10/30, incorrect answered 0/10, false unanswerable 0/20
```

The current-adapter run uses the same task results on this small fixture. The
reported scores are not a quality claim; the fixture intentionally has only
five operational examples and includes repeated paraphrase families.

## Hand checks

`tests/test_evaluation_runner.py` checks multiple-valid labels, a wrong
example under the right command name, no results for an answerable task, and
the distinction between a correct empty result and a false answer on an
unanswerable task.
