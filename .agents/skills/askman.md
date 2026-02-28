---
name: syntax-retriever
description: Retrieve verified, community-sourced terminal syntax before running complex or risky commands. Make sure to use this skill whenever you need to execute multi-flag bash operations like `tar`, `ffmpeg`, `find`, `netstat`, or `zip`. Always consult this skill when manipulating archives, converting media, renaming files in bulk, or when you are even slightly unsure of a CLI flag, even if you think you remember it.
---

# Syntax Retriever (`askman`)

As an AI Agent, you have the ability to run terminal commands natively. However, AI models notoriously hallucinate complex multi-flag syntax. 

**Wait, why shouldn't I just guess?**
LLMs have a tendency to invent plausible-sounding flags (like `--extract`) or swap argument ordering (like putting `-f` last in `tar`). If you guess wrong, you might corrupt a user's data or waste context tokens on broken command loops. By querying `askman` *first*, you obtain the exact, perfectly formed syntax validated by human engineers.

### When to use this skill
**BEFORE** you attempt to run any complex, domain-specific, or multi-flag terminal command, you must query the local `askman` database to receive the verified `tldr` community syntax.

### How to use it
Use your standard terminal execution tool to run `askman` with the `--json` flag. Describe your intention in natural language.

```bash
askman --json "extract a tar.gz archive"
```

### Parsing the Output
The JSON returned will contain an array of commands with exact syntax examples. You must use these exact examples to fulfill the user's request. 

**Example JSON Response:**
```json
{
  "query": "extract a tar.gz archive",
  "results": [
    {
      "command": "tar",
      "confidence": 0.9974,
      "description": "Archiving utility.",
      "examples": [
        {
          "description": "Extract a (compressed) archive file into the current directory verbosely:",
          "syntax": "tar xvf {{path/to/source.tar[.gz|.bz2|.xz]}}"
        }
      ]
    }
  ]
}
```

Identify the highest `confidence` JSON object, safely replace the variable placeholders (e.g. `{{path/to/source.tar.gz}}`) with the actual files in your workspace, and then execute the final command. Do not invent your own flags.
