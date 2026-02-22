# askman
A simple, offline CLI tool that finds terminal commands from natural language descriptions. Just describe what you want to do.

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

On first run, `askman` downloads a small embedding model and command database.

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

Want to refresh the database with the absolute latest commands?
```bash
cargo run --bin import_tldr --features="dev"
```
This automatically fetches the newest data from the tldr repository, extracts it, and generates a fresh database for your system.