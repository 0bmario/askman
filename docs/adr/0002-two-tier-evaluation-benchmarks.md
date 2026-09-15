# Two-tier retrieval evaluation

Keep `evaluation-v1` immutable as a small regression benchmark. Create `evaluation-v2` with 120 new tasks split into 60 development tasks and 60 hidden holdout tasks; each split contains exactly 30 answerable and 30 unanswerable tasks. Balance the tasks across target platforms and intent families, and keep each paraphrase family within one split.

Authors must freeze prompts before inspecting retrieval outputs. Labels are relative to the pinned corpus and requested platform: an answerable task has at least one acceptable corpus example, while an unanswerable task has none. Tune only on development tasks and freeze the retrieval configuration before opening holdout results.
