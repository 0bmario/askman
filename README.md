# 📚 askman

**A simple, offline CLI tool for developers who want to use Unix/Linux terminal commands without googling/AI-ing every time or checking the [man pages](https://en.wikipedia.org/wiki/Man_page).**

---

## 🤔 Why?

I didn't want to leave the terminal to search for the right command, and man pages aren't always "easy" to read.

---

## 🤖 What is askman?

`askman` lets you ask natural language questions about Unix/Linux commands and get helpful, example-driven answers — all offline.

---

## 💡 Example Usage

```bash
askman how to move all files to /docs  
```

**Output:**
```bash
mv
Move or rename files and directories. More information: <https://www.gnu.org/software/coreutils/manual/html_node/mv-invocation.html>.

Examples:
  Move a file or directory into an existing directory:
   mv {{path/to/source}} {{path/to/existing_directory}}

  Move multiple files into an existing directory, keeping the filenames unchanged:
   mv {{path/to/source1 path/to/source2 ...}} {{path/to/existing_directory}}
```

---

## 🏗️ MVP

- Uses dataset commands created from [tldr-pages common](https://github.com/tldr-pages/tldr/tree/main/pages/common) folder 
- Provides semantic search for command examples

---

## 📦 Installation

Make sure you have [Rust and Cargo installed](https://www.rust-lang.org/tools/install).

Then run:

```bash
cargo install --git https://github.com/cito-lito/askman
```

This will install `askman` with a pre-built database.

---

## 🔧 Building Your Own Database

If you want to customize the command database:

1. Clone the repository:

2. Place your tldr-pages into the `common/` directory:
   Make sure the files follow the format of the [tldr-pages](https://github.com/tldr-pages/tldr/blob/main/CONTRIBUTING.md#markdown-format).

3. Build and run the import tool:

```bash
cargo run --bin import_tldr
```

This will create a new `commands.db` file with your custom command set.

## Features (planned)

- Understands natural language questions
- Provides example-driven answers
- Fast, offline

---

## 📄 License

This project is licensed under the terms of the [MIT License](LICENSE).

---

**Contributions and feedback are welcome!**



