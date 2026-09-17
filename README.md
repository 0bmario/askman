# askman

An offline CLI that finds terminal commands from natural language descriptions. Describe what you want to do and `askman` returns the closest matching command with examples.

<p align="center">
  <img src="./askman-demo.gif" alt="askman demo" width="700">
</p>

## Installation

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/0bmario/askman/v0.3.3/install.sh | bash

```

### Cargo

```bash
cargo install --git https://github.com/0bmario/askman
```

After installing, provision the compatible matching bundle once while online:

```bash
askman setup
```

Setup downloads the bundle and manifest pinned to this CLI release, verifies
all component metadata and digests, then activates it atomically. Searches do
not access the network. Update explicitly with `askman update`; restore the
previous valid bundle with `askman rollback`.

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
- Your query is embedded locally with [AllMiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), then matched against a SQLite database through [sqlite-vec](https://github.com/asg017/sqlite-vec).
- The active matching bundle contains the corpus, lexical index, dense index,
  and pinned embedding assets. Everything after explicit setup/update runs on
  your machine.

## Uninstall

First, remove cached data:

```bash
askman --clean
```

Then remove the binary itself: `rm ~/.local/bin/askman` or if installed via cargo `cargo uninstall askman`.

## Acknowledgments

Thanks to the [tldr-pages](https://github.com/tldr-pages/tldr) project. The command data used by `askman` comes from their collection of simplified examples.

## Developer tldr subset runner

The milestone-1 corpus runner is separate from the shipping `askman` CLI. It
only consumes a provisioned local snapshot and writes the explicitly supplied
output path; it does not download tldr or touch Askman's installed database.
See [the reproducible corpus instructions](docs/reproducibility/tldr-subset.md)
and the [full-corpus build record](docs/reproducibility/tldr-full-corpus.md).
The frozen evaluation dataset and offline baseline runner are documented in
[the evaluation record](docs/reproducibility/evaluation-baseline.md).
The public release benchmark is documented in
[the evaluation-v2 freeze record](docs/reproducibility/evaluation-v2.md).
The expanded corpus-backed release evidence is documented in
[the evaluation-v2 expanded record](docs/reproducibility/evaluation-v2-expanded.md).
The dense retrieval candidate is documented in the
[dense retrieval instructions](docs/reproducibility/dense-retrieval.md).
The hybrid comparison, bounded development tuning, and frozen operating point
are documented in the [hybrid retrieval instructions](docs/reproducibility/hybrid-retrieval.md).
The held-out evidence protocol and machine-readable report are documented in
the [held-out evidence instructions](docs/reproducibility/heldout-evidence.md).
The immutable matching bundle build and validation are documented in the
[matching bundle instructions](docs/reproducibility/matching-bundle.md).
The Better Askman terminology is defined in the [context glossary](docs/CONTEXT.md),
and release decisions are recorded in the [ADRs](docs/adr/).
