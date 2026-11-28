# askman

[![CI](https://github.com/0bmario/askman/actions/workflows/ci.yml/badge.svg)](https://github.com/0bmario/askman/actions/workflows/ci.yml)
[![crates.io](https://img.shields.io/crates/v/askman.svg)](https://crates.io/crates/askman)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/0bmario/askman/blob/main/LICENSE)

An offline CLI that finds terminal commands from natural language descriptions. Describe what you want to do and `askman` returns the closest matching command with examples.

<p align="center">
  <img src="https://raw.githubusercontent.com/0bmario/askman/main/askman-demo.gif" alt="askman demo" width="700">
</p>

## Installation

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/0bmario/askman/v0.3.5/install.sh | bash

```

### Cargo

```bash
LIBONNXRUNTIME_NO_PKG_CONFIG=1 cargo install askman
```

The variable keeps askman on its bundled ONNX Runtime even when a system one
(for example Homebrew's `onnxruntime`) is installed; without it, such a build stops
with this instruction. `install.sh` binaries are not affected.
Linking a system ONNX Runtime is not supported: askman is built and verified only with its bundled ONNX Runtime 1.20.

On first run, `askman` downloads a small embedding model and the commands database (`commands-v2.db`). After that, lookups run offline.

## Usage

```bash
askman move files to docs
```

By default, results are filtered to your host OS. Override that when you need a command for a different system:

```bash
askman --linux restart systemd
askman --osx flush dns
askman --windows clear dns cache
```

## How it works

- `askman` uses semantic search to match your query to real command examples from [tldr-pages](https://github.com/tldr-pages/tldr).
- Your query is embedded locally with an int8-quantized [AllMiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), then matched against a SQLite database through [sqlite-vec](https://github.com/asg017/sqlite-vec).
- After the initial model and database download, everything runs on your machine.

## Uninstall

First, remove cached data:

```bash
askman --clean
```

Then remove the binary itself: `rm ~/.local/bin/askman` or if installed via cargo `cargo uninstall askman`.

## Acknowledgments

Thanks to the [tldr-pages](https://github.com/tldr-pages/tldr) project. The command data used by `askman` comes from their collection of simplified examples.

## Rebuilding the Database

```bash
cargo run --bin import_tldr --features dev
```

This fetches the latest tldr pages, extracts them, and builds a fresh `commands-v2.db` for your system. It also imports the pages in `pages/` that tldr does not have yet.
