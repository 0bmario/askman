# askman 

A simple, offline CLI tool for developers who want to look up Linux, macOS, and Windows terminal commands using natural language, without leaving the terminal or digging through the man pages. Just ask what you want to do, and get the command you need.

## Usage

```bash
askman how to move all files to /docs
```

```
mv
Move or rename files and directories.

Examples:
  Move a file or directory into an existing directory:
   mv path/to/source path/to/existing_directory

  Move multiple files into an existing directory, keeping the filenames unchanged:
   mv path/to/source1 path/to/source2 ... path/to/existing_directory
```

By default, results are filtered to your host OS. If you need a command for a different system, override it with flags:
```bash
askman --linux how to restart systemd
askman --osx how to flush dns
askman --windows how to clear dns cache
```

## Installation

Ensure you have [Rust](https://rust-lang.org/tools/install/) installed, then run:
```bash
cargo install --git https://github.com/0bmario/askman
```

On your first query, `askman` will automatically download and cache a fast semantic search model and a curated database of commands. Everything runs locally on your machine after that!

## Uninstall

To cleanly remove the cached models, database, and the CLI executable:
```bash
askman --clean && cargo uninstall askman
```

## Rebuilding the Database

Want to refresh the database with the absolute latest commands?
```bash
cargo run --bin import_tldr --features="dev"
```
This automatically fetches the newest data from the tldr repository, extracts it, and generates a fresh database for your system.

## Acknowledgments

A huge thank to the [tldr-pages](https://github.com/tldr-pages/tldr) project! `askman`'s command data is entirely sourced from their dope, community-driven collection of simplified examples :raised_hands: