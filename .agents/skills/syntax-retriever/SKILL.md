---
name: syntax-retriever
description: MUST USE before running complex or unfamiliar terminal commands.
---

# Syntax Retriever (askman)

Before executing complex, multi-flag, or unfamiliar terminal commands, query `askman` to retrieve verified syntax.

## Core Rules

1. **Decompose First**: Query for specific actions, not complex pipelines. (e.g., query `"find by size"` and `"find and delete"` separately, then compose).
2. **Target Intent**: Query for what the command *does* (e.g., `"extract tar.gz"`). If you know the tool, include it: `"awk sum column"`.
3. **No Hallucinations**: Use `askman` syntax exactly as returned. Fallback to `man <tool>` or `<tool> --help` if: confidence is **<0.8**, `intent.status` is `warn`, query names a tool and top `command` is not that tool family, or top result has `<3` examples for a complex task.
4. **Hyphenated Subcommands**: `tldr-pages` indexes subcommands as `tool-subcommand`. When the base tool page is generic, try the hyphenated form (e.g., `"kubectl-rollout"`, `"git-stash"`) to get the dedicated, richer page.

## Usage

```bash
askman --json "git-rebase"      # Subcommand form
askman --json "jq filters"      # Intent form
```

Select the result where `command` family and `platform` match intent.
