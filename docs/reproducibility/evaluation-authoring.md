# Evaluation authoring record

This file records the original `evaluation-v1` fixture. The frozen
`evaluation-v2` release benchmark has a separate [freeze record](evaluation-v2.md)
and provenance file.

The task intentions below were written before inspecting the pinned corpus.
After corpus inspection, the separate split files record whether each task is
answerable, its acceptable example IDs and the correctness rationale.

| Split | Family | Intent |
| --- | --- | --- |
| dev | copy-dev | copy a source path to a destination |
| dev | search-dev | search text recursively under a path |
| dev | clipboard-dev | transfer input to a macOS clipboard |
| dev | coverage-dev | exercise missing, navigation-only and platform-inapplicable coverage |
| dev | audit-dev | retain previously inspected prompts and missing capabilities as development regressions |
| dev | platform-dev | check platform-specific absence without borrowing holdout answers |
| holdout | editor-holdout | launch the text editor against a path |
| holdout | windows-holdout | emit a formatted value on Windows |
| holdout | missing-holdout | request capabilities absent from the pinned selection |
| holdout | platform-holdout | check platform-specific absence |
| holdout | reference-holdout | distinguish unsupported page/reference requests |
| holdout | ambiguity-holdout | distinguish unsupported requests with overlapping wording |

The four previously inspected prompts remain development-only regression cases:
`move files to docs`, `restart systemd`, `find text in compressed logs`, and
`make my database fast without changing anything`. The holdout file is kept
separate and requires explicit access, so normal development runs cannot load
its labels. The per-task intent freeze is recorded separately in
`tests/fixtures/evaluation/task-intents-v1.json`; it contains no questions,
labels, rationales or answer IDs.
