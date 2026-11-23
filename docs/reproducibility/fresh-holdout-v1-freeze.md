# Fresh holdout v1 freeze

Frozen 2026-09-26T13:05:01Z. At freeze time, status was **unscored**. The
split was later scored once after explicit user authorization. Frozen labels
remain unchanged; manifest state records freeze-time status.

## Contents

- 60 newly authored intents: 15 each for common, Linux, macOS, and Windows.
- 30 answerable and 30 abstention tasks; each platform has 7 or 8 positives.
- Corpus pinned to tldr-pages `e1cb966e711d73c42d75e79834be7e4dc17264ef`, parser `tldr-subset-v4`, 142 visible examples.
- Prompt-only final intents and labels are separate artifacts. Prior task prompts and retrieval results were not used to author these intents.

## Label review and reconciliation

A source/rationale pass and an independent prompt-only label pass reviewed the set. The blind pass produced 60 labels (30 answerable, 30 abstain). We preserved its original output and the prompt-only intent freeze. Before final freeze, we reconciled source-ID and wording issues:

- `common-positive-03`: both recursive-copy records are accepted; both match the requested nesting behavior.
- `common-positive-04`: the source-ID derivation showed the author's interactive-copy ID is correct; the blind review's ID pointed to symbolic-link handling despite its overwrite-prompt rationale.
- `linux-positive-08`: the intent now asks for the full service status report; an independent recheck found only the named-unit `systemctl status` record matches.
- `osx-positive-04`: the source page's other clipboard example contains `find -type t`, which the installed `find` rejects (`unknown type`). The task now targets the valid file-redirection `pbcopy` example; independent recheck found one matching record.
- Two negative rationales were tightened to distinguish uncompressed tar creation and line-only `wc -l` from the requested gzip archive and per-file line/word/byte counts.

These are authoring-time label/source checks, not retrieval scores. The final intent freeze is v2; v1 is preserved as a superseded prompt-only artifact. The v1 blind label output remains raw evidence, with final adjudications recorded here and in [fresh-holdout-v1-label-reconciliation-v2.json](artifacts/fresh-holdout-v1-label-reconciliation-v2.json) and the revised-intent review artifact.

## Scoring record

Candidate 3494a11 was scored once against main by the canonical release gate.
Success@1 was 13/30 to 15/30; Success@3 fell 19/30 to 15/30. Incorrect
answered tasks rose 7/26 to 10/25, while false answers fell 13/30 to 8/30.
The one-sided 95% paired-bootstrap lower bound was -3.3 points. The decision
was inconclusive; this split is consumed and must not be reused or used to
tune a candidate. The frozen dataset and manifest were not changed.

Full evidence:
[main-vs-retrieval-v2-focused-fresh-holdout-v1.json](artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v1.json)
and
[rendered report](artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v1.md).

## Digests

See [fresh-holdout-v1.manifest.json](../../tests/fixtures/evaluation/fresh-holdout-v1.manifest.json) for SHA-256 values, corpus identity, distribution, and structural-check results. Frozen inputs: dataset `7fe11e153b64941c91233b756543487ebdd34e17bcca7b935a55f8f16a6fb2a0`; final intents `d41afe4e0fdf3b5fdcae9bf37bbab97f2966b54a99643fef61877590b4e015d5`; corpus manifest `3548a0b5b4190c144354f1ee7cc505bdae3c3c877a7d409bb32a94900c637b85`.

Freeze manifest SHA-256: `7463ccb782cf971b4893f369c899f408212306020c68e471b72c146b2da68f1a`.
