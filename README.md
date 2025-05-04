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
askman how to move all .pdf files to /docs
```

**Output:**
```bash
Use mv to move files, or cp to copy them:

mv *.pdf /docs
cp *.pdf /docs
```

---

## 🏗️ MVP

- Uses a basic dataset of examples
- Works completely offline

---

## 📦 Installation

Make sure you have [Rust and Cargo installed](https://www.rust-lang.org/tools/install).

Then run:

```bash
cargo install --git https://github.com/cito-lito/askman
```

---

## Features (planned)

- Understands natural language questions
- Provides example-driven answers
- Fast, offline, and privacy-friendly

---

## 📄 License

This project is licensed under the terms of the [MIT License](LICENSE).

---

**Contributions and feedback are welcome!**



