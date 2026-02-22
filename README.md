# askman
A simple, offline CLI tool that finds terminal commands from natural language descriptions. Just describe what you want to do.

<p align="center">
  <img src="./askman-demo.gif" alt="askman demo" width="700">
</p>

## Installation

Requires [Rust](https://rust-lang.org/tools/install/):

```bash
cargo install --git https://github.com/0bmario/askman
```

On first run, `askman` downloads a small search model and command database. Everything runs offline after that.

## Usage

```bash
askman <description of the needed command>
```

Results are filtered to your OS by default. Override with flags:

```bash
askman --linux how to restart systemd
askman --osx how to flush dns
askman --windows how to clear dns cache
```

## How it works

- `askman` embeds your query into a vector and matches it against pre-embedded command examples.
- All command data comes from [tldr-pages](https://github.com/tldr-pages/tldr), embeddings are generated with [AllMiniLM-L6-V2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), and vector DB created with [sqlite-vec](https://github.com/asg017/sqlite-vec).
- Everything runs locally after setup.

## Uninstall

```bash
askman --clean && cargo uninstall askman
```

## Acknowledgments

Command data sourced from the [tldr-pages](https://github.com/tldr-pages/tldr) project. Semantic search powered by [AllMiniLM-L6-V2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) and [sqlite-vec](https://github.com/asg017/sqlite-vec).

## License

MIT