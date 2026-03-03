# askman

**An offline terminal command syntax engine for AI Agents.**

`askman` constrains agents to community-verified syntax (sourced from [tldr-pages](https://github.com/tldr-pages/tldr)). It translates natural language goals into strict, executable JSON payloads.

Built-in guardrails (semantic confidence scores and an engine that checks if the intent matches the documentation) explicitly tell the agent when to abort a guess and fallback to reading `man` pages or `tool --help`.

## How it Works

1. Feed `askman` a natural language goal: `askman --json "kubectl force delete namespace"`
2. It runs offline semantic vector search against an embedded SQLite database.
3. It returns perfectly formatted syntax, with a `confidence` score and `intent.status`.
4. If `status: warn` or `confidence < 0.8`, the agent knows to abort and fallback to manual docs.

### Target Agents

`askman` is designed for **autonomous, terminal-operating AI Agents** that need a reliable, way to retrieve complex command syntax without risking system destruction or hallucinated flags.

#### Agent Integration

Give your agent access to the `askman` binary and add [`.agents/skills/syntax-retriever/SKILL.md`](./.agents/skills/syntax-retriever/SKILL.md) to its context.

---

## Installation

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/0bmario/askman/main/install.sh | bash
```

### Cargo

```bash
cargo install --git https://github.com/0bmario/askman
```

## Uninstall

First, remove cached data (embedding model and database):

```bash
askman --clean
```

Then remove the binary itself:

- **If installed via `install.sh`:**

  ```bash
  rm ~/.local/bin/askman
  ```

- **If installed via `cargo`:**

  ```bash
  cargo uninstall askman
  ```

## Acknowledgments

Kudos to the [tldr-pages](https://github.com/tldr-pages/tldr) project. The used command data is sourced from their collection of simplified examples :raised_hands:

## Rebuilding the Database

```bash
cargo run --bin import_tldr --features="dev"
```

This automatically fetches the newest data from the tldr repository, extracts it, and generates a fresh commands database.

*(askman can also be used as a CLI lookup tool by human devs by omitting the `--json` flag.)*

<p align="center">
  <img src="./askman-demo.gif" alt="askman demo" width="700">
</p>
