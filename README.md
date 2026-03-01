# askman
**The offline, semantic search engine for the terminal.**

`askman` translates natural language descriptions into exact terminal commands. Built as a dual-purpose tool, it serves as a CLI lookup for human devs, and as a context provider for AI Agents / RAG pipelines.

<p align="center">
  <img src="./askman-demo.gif" alt="askman demo" width="700">
</p>

## Installation

### macOS / Linux (recommended)

```bash
curl -sSL https://raw.githubusercontent.com/0bmario/askman/main/install.sh | bash
```

### From source

Requires [Rust](https://rust-lang.org/tools/install/):

```bash
cargo install --git https://github.com/0bmario/askman
```

On first run, `askman` downloads a small embedding model and commands database.

## Usage

```bash
askman move files to docs
```

By default, results are filtered to your host OS. If you need a command for a different system, override it with flags:
```bash
askman --linux restart systemd
askman --osx flush dns
askman --windows clear dns cache
```

### For AI / LLM Agents (JSON Output)

Use `askman` as an offline context provider for AI Agents. The `--json` flag returns a strict, token-efficient schema containing community-verified syntax: [tldr-pages](https://github.com/tldr-pages/tldr) and a calibrated `confidence` score (0.0 to 1.0):

```bash
askman --json "extract a tar.gz archive"
```

**Output:**
```json
{
  "query": "extract a tar.gz archive",
  "results": [
    {
      "command": "tar",
      "confidence": 1.00,
      "description": "Archiving utility. Often combined with a compression method, such as `gzip` or `bzip2`.",
      "examples": [
        {
          "description": "Extract a (compressed) archive file into the current directory verbosely:",
          "syntax": "tar xvf {{path/to/source.tar[.gz|.bz2|.xz]}}"
        },
        {
          "description": "Extract a (compressed) archive file into the target directory:",
          "syntax": "tar xf {{path/to/source.tar[.gz|.bz2|.xz]}} {{[-C|--directory]}} {{path/to/directory}}"
        }
      ]
    },
    {
      "command": "unzip",
      "confidence": 1.00,
      "description": "Extract files/directories from Zip archives.",
      "examples": [
        {
          "description": "Extract all files/directories from specific archives into the current directory:",
          "syntax": "unzip {{path/to/archive1.zip path/to/archive2.zip ...}}"
        }
      ]
    }
  ]
}
```

### Agent Integration (Skill)
Add the [`.agents/skills/askman.md`](./.agents/skills/askman.md) file to your agent's skill directory.


## How it works

- `askman` uses semantic search to match your query to real command examples from [tldr-pages](https://github.com/tldr-pages/tldr).
- Input is embedded into a vector using a local [AllMiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) model, then matched against a pre-built SQLite database via [sqlite-vec](https://github.com/asg017/sqlite-vec) cosine distance.
- Everything runs on your machine after the initial setup.

## Uninstall

First, remove cached data (models and database):
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