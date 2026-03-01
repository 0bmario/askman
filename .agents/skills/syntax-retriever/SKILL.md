---
name: syntax-retriever
description: >-
  MUST USE before running any multi-flag or unfamiliar terminal command.
  Retrieves verified community-sourced syntax from a local database.
---

# Syntax Retriever

**Rule:** Before executing any complex, multi-flag, or unfamiliar terminal
command, you MUST query `askman` to retrieve verified syntax. Do NOT guess flags.

### When to use
BEFORE running a terminal command where you are unsure of exact flags or argument ordering.

### How to use

```bash
askman --json "extract a tar.gz archive"
```

If you already know the command name, include it in the query for better results:
```bash
askman --json "wget download entire website"
```

### Parsing the output

Example response:
```json
{
  "query": "extract a tar.gz archive",
  "results": [
    {
      "command": "tar",
      "confidence": 0.99,
      "description": "Archiving utility.",
      "examples": [
        {
          "description": "Extract an archive verbosely:",
          "syntax": "tar xvf {{path/to/source.tar.gz}}"
        }
      ]
    }
  ]
}
```

Select the result whose `command` best matches the user's intent.
Replace `{{placeholders}}` with actual paths from the workspace, then execute.
Do not invent flags beyond what `askman` returns.

### Multi-step pipelines
If the task requires chaining multiple commands (e.g., `find | xargs kill`),
query `askman` for each command separately, then compose the pipeline yourself.

### Fallback
If `askman` returns an empty `results` array or the binary is not found,
tell the user and ask for guidance. Do NOT guess the syntax.
