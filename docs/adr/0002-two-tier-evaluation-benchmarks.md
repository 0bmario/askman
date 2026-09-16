# Two-tier retrieval evaluation

Keep `evaluation-v1` immutable as a small regression benchmark. Create `evaluation-v2` with exactly 120 new tasks: 60 development tasks and 60 hidden holdout tasks. Each split contains exactly 30 answerable and 30 unanswerable tasks. Cover all four target platforms: `common`, `linux`, `osx`, and `windows`; use scenario families for grouping and keep each paraphrase family within one split.

Record benchmark provenance for every task: a public, license-compatible user intent, stable ID, and rationale; exclude private data and copied candidate answers. Authors must author and freeze prompts before inspecting retrieval outputs. Labels are relative to the pinned corpus and requested platform: an answerable task has at least one acceptable corpus example, while an unanswerable task has none. Tune only on development tasks and freeze the retrieval configuration before opening holdout results.
