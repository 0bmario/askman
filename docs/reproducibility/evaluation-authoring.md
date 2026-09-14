# Evaluation authoring record

The task intentions below were written before inspecting the pinned corpus.
After corpus inspection, the separate split files record whether each task is
answerable, its acceptable example IDs and the correctness rationale.

| Split | Family | Intent |
| --- | --- | --- |
| dev | copy-dev | copy a source path to a destination |
| dev | search-dev | search text recursively under a path |
| dev | edit-dev | open or edit a text file |
| dev | clipboard-dev | transfer input to a macOS clipboard |
| dev | windows-dev | print formatted Windows output |
| dev | coverage-dev | exercise missing, navigation-only and platform-inapplicable coverage |
| holdout | path-duplication | copy paths while varying platform and wording |
| holdout | tree-search | search a path with recursive grep syntax |
| holdout | editor-launch | launch the text editor against a path |
| holdout | clipboard-transfer | copy file or standard-input content on macOS |
| holdout | formatted-output | emit a formatted value on Windows |
| holdout | missing-coverage | request capabilities absent from the pinned selection |

The four previously inspected prompts remain development-only regression cases:
`move files to docs`, `restart systemd`, `find text in compressed logs`, and
`make my database fast without changing anything`. The holdout file is kept
separate and requires explicit access, so normal development runs cannot load
its labels.
