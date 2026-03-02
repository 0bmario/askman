---
name: syntax-retriever
description: >-
  MUST USE before running any multi-flag or unfamiliar terminal command that can lead to unrecoverable states.
  Retrieves verified community-sourced syntax from a local database.
---

# Syntax Retriever

**Rule:** Before executing any complex, multi-flag, or unfamiliar terminal
command, you MUST query `askman` to retrieve verified syntax. Do NOT guess flags.

## Strategy (Crucial)

**Mental Model:** The search engine does not "understand" instructions or build pipelines; it performs semantic similarity matching against community-curated `tldr` pages. You must query to match *how commands are described* in documentation.

- **Query for what it does, not the exact constraints:** For example, instead of querying `"find files larger than 50MB and delete them"` (which is too specific), query `"find files by size"`. Find the size flag (`-size`), then run a second query for `"find and delete files"` to find the delete flag (`-delete`), and compose them yourself.
- **Break down complex pipelines:** `askman` is a syntax verifier, not an intent interpreter. If you need `lsof | xargs kill`, query for `lsof` and `kill` independently to verify their flags.
- **Do not invent flags:** Use your AI reasoning to apply the syntax to your specific scenario (paths, wildcards, regex patterns), but **never guess or hallucinate the flags themselves.**
- **The "Missing Flag" Fallback:** `askman` searches `tldr` pages, which sometimes omit highly advanced or niche flags (like `tar --wildcards`). If `askman` returns nothing or irrelevant results, **do not hallucinate the flag**. Instead, run `man <command>` or `<command> --help` to safely read the official documentation.

## How to use

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
  "os": "osx",
  "results": [
    {
      "command": "tar",
      "platform": "common",
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
If you need commands for a remote machine, prefer results where `platform` matches that machine.
Replace `{{placeholders}}` with actual paths from the workspace, then execute.
