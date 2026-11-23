# Operational soft-fit v1 — frozen protocol

## Question

Does a small, source-backed compatibility penalty improve first-result correctness while preserving the current candidate’s coverage, top-three usefulness, false-answer rate, platform behavior, offline operation, latency, and memory?

## Fresh development cohort

- Prompt pool: 60 prompts, 12 new scenario families, 15 per platform; author-pool SHA-256 `8e70b6e4e73d8a0c066d33e2a713899abc7ccd191e0201b7e5c5cad99ad5b202`.
- Labels are independently audited against the pinned parser-v4 source pages. The audit, not the author’s intended balance, determines answerability and valid source examples.
- Corpus: manifest-v4, 24 pages and 142 operational examples, source revision `e1cb966e711d73c42d75e79834be7e4dc17264ef`, source digest `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`, manifest-file SHA-256 `3548a0b5b4190c144354f1ee7cc505bdae3c3c877a7d409bb32a94900c637b85`.
- Freeze the audited dataset, labels, configs, source hashes, and protocol before either arm runs. Preserve failed preflight freezes; do not overwrite them.

## One-factor comparison

Use the same pinned corpus bundle and the same main-compatible embeddings, focused-v2 query rules, candidate budget 8, raw-distance cutoff 0.60, existing 0.05 lexical overlap adjustment, platform selection, abstention guards, and top-three display limit.

- Control: `operational-soft-fit-dev-v1-control-config.json`; operational penalty off.
- Treatment: `operational-soft-fit-dev-v1-treatment-config.json`; add `0.05 × unsupported_fraction` to lexical-adjusted distance.
- `unsupported_fraction` is the share of detected action/constraint rules not evidenced by the candidate’s page command, example description, or command. Page overview text is excluded. If no rule is detected, the penalty is zero.
- This is rank-only: it cannot filter candidates, change the raw-distance cutoff, or change abstention. No rule, alias, threshold, query, corpus, or weight sweeps are allowed.

## Decision criteria

Promote this ranking change only if treatment gains at least two supported-task Success@1 tasks over both the unchanged control and installed main, aggregate Success@3 and per-platform Success@1/Success@3 do not fall below either reference, false answers do not increase, and coverage is unchanged from control and no lower than main. Also require zero network-denied CLI failures and fresh/warm p95 latency and peak memory within 20% of both references. Otherwise reject and preserve the result; do not tune on this cohort.

This custom cohort is development-only. It cannot authorize release or access holdout. Any independent evaluation requires a new unseen holdout, a frozen candidate, and fresh explicit user authorization before scoring. Do not tune on holdout results.
