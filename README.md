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

### From source (any platform)

Requires [Rust](https://rust-lang.org/tools/install/):

```bash
cargo install --git https://github.com/0bmario/askman
```

On first run, `askman` downloads a small embedding model and command database. Everything runs offline after that.

## Usage

```bash
askman <description action or command>
```

By default, results are filtered to your host OS. If you need a command for a different system, override it with flags:
```bash
askman --linux restart systemd
askman --osx flush dns
askman --windows clear dns cache
```

## Uninstall

First, remove cached data (models and database):
```bash
askman --clean
```

Then remove the binary itself:

- **If installed via `install.sh`:**
  ```bash
  sudo rm /usr/local/bin/askman
  ```
- **If installed via `cargo`:**
  ```bash
  cargo uninstall askman
  ```

## Rebuilding the Database

Want to refresh the database with the absolute latest commands?
```bash
cargo run --bin import_tldr --features="dev"
```
This automatically fetches the newest data from the tldr repository, extracts it, and generates a fresh database for your system.

## Acknowledgments

A huge thank to the [tldr-pages](https://github.com/tldr-pages/tldr) project! `askman`'s command data is entirely sourced from their dope, community-driven collection of simplified examples :raised_hands: