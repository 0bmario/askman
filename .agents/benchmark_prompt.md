# Agent Task: Benchmark the `askman` Skill

You are an AI coding agent working in the `/Users/mmo/fun/Rust/askman` project.

**Your goal:** Run a structured benchmark comparing your "blind guess" against `askman --json` output for 20+ diverse terminal command scenarios. Document whether `askman` helps agents produce more correct, safe, and precise commands.

---

## Context

`askman` is a CLI tool that returns verified terminal command syntax as JSON. It is invoked as:
```bash
askman --json "natural language query"
```

**Key JSON fields:**
- `"os"` — host OS auto-detected
- `"platform"` — which OS this command belongs to (`linux`, `osx`, `windows`, `common`)
- `"confidence"` — 0.0 to 1.0 match score
- `"examples[].syntax"` — verified command with `{{placeholder}}` tokens

**Read the skill file first:** `.agents/skills/syntax-retriever/SKILL.md`

---

## Test Protocol

For each scenario:
1. **Write your blind guess** — what command would you use without any tool?
2. **Run `askman --json "query"`** and capture the output
3. **Verdict:**
   - `askman wins` — better, safer, or more correct
   - `AI wins` — your guess was clearly superior
   - `Tie` — both equivalent
   - `askman miss` — wrong/irrelevant (confidence < 0.5 or empty results)

**Risk flags to note:** wrong flags, deprecated tools, missing safety flags (dry-run, `-n`), platform mismatch.

---

## Test Scenarios

### Easy
1. `"list all open ports"`
2. `"count lines in a file"`
3. `"show current disk usage"`
4. `"print environment variables"`
5. `"check if a process is running"`

### Medium
6. `"rsync files to remote server excluding node_modules"`
7. `"watch a log file in real time"`
8. `"find and replace text in all files recursively with sed"`
9. `"create a symbolic link"`
10. `"change file permissions recursively"`
11. `"extract specific lines from a log file"`
12. `"kill process listening on port 3000"`

### Hard (hallucination-prone)
13. `"ffmpeg convert video to gif"`
14. `"openssl generate self-signed certificate"`
15. `"docker copy files between containers"`
16. `"git cherry-pick a range of commits"`
17. `"systemctl enable and start a service"`
18. `"iptables allow traffic on port 443"`
19. `"compress a directory with tar and split into 1GB parts"`
20. `"set up ssh key-based authentication"`

### Bonus (cross-platform)
21. `"firewall block port on mac"` — check for `pf`/`pfctl`
22. `"schedule a recurring task on linux"` — `cron` vs `systemd timer`?

---

## Report Format

Create `benchmark_results.md` in the project root with:

### 1. Per-test table

| # | Scenario | My Blind Guess | Askman Returns | Winner | Key Difference |
|---|---|---|---|---|---|

### 2. Final Scorecard

| askman wins | AI wins | Ties | Misses |
|---|---|---|---|

### 3. Pattern Analysis
- Where does askman consistently add value?
- Where does it fail or miss?
- Any low confidence results (< 0.5)?
- Any platform surprises (`"platform": "linux"` when on macOS)?

### 4. Token Efficiency Note
Did askman prevent any likely hallucinations that would have cost retries?

---

## Notes

- `askman` is in PATH; also available as `cargo run --bin askman --` from project root
- Always use `--json` flag
- `"results": []` or confidence < 0.5 = **miss**, mark and move on
- For pipeline commands, query each command **separately** as the skill instructs
