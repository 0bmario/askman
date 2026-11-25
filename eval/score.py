"""Score askman retrieval on the eval set against the installed commands database.

Usage:
  cargo build --release --example rank
  python3 eval/score.py [--split dev|check|check-v1|all] [--rank target/release/examples/rank]

askman-eval-v3.json holds 220 real-style queries scored against db-v2
(commands-v2.db): 150 `dev`, 55 held-back `check` and the 15 v1 check queries
as `check-v1` (spent: scored for 0.3.6, E1 and E2). v3 kept all 100 v2 queries
and added 80 dev and 40 check queries (q101-q220), split by a seeded shuffle.
- accept: commands counted as correct (lowercase); empty means the right answer
  is "No good matches found."
- foreign: commands that are wrong-platform answers for the listed targets.
- Tune on dev only. Score check once per ship decision and record it in the PR.
- Log accept-list edits in the JSON `changelog`; bump the version for larger changes.

v0.3.7 baseline, dev: top-1 37/70, top-3 54/70, wrong-platform top-1 3.
"""
import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--eval", default=Path(__file__).with_name("askman-eval-v3.json"))
parser.add_argument("--rank", default="target/release/examples/rank")
parser.add_argument("--split", default="dev", choices=["dev", "check", "check-v1", "all"])
args = parser.parse_args()

doc = json.load(open(args.eval))
queries = [q for q in doc["queries"] if args.split == "all" or q["split"] == args.split]
stdin = "".join(f"{q['target']}\t{q['query']}\n" for q in queries)
lines = subprocess.run([args.rank], input=stdin, capture_output=True, text=True, check=True).stdout.splitlines()

total, by_platform = Counter(), {}
for query, line in zip(queries, lines):
    ranked = [cell.split("|") for cell in line.split("\t") if cell]
    commands = [cell[0].lower() for cell in ranked]
    accept = set(query["accept"])
    if accept:
        top1 = bool(commands) and commands[0] in accept
        top3 = any(c in accept for c in commands[:3])
        # The CLI prints rank 1, plus ranks 2-3 only within 0.05 of rank 1's score.
        shown = [c[0].lower() for c in ranked[:3] if float(c[1]) - float(ranked[0][1]) < 0.05]
        displayed = any(c in accept for c in shown)
    else:  # unanswerable: the right result is no answer
        top1 = top3 = displayed = not commands
    wrong_platform = bool(commands) and query["target"] in doc["foreign"].get(commands[0], [])
    counts = by_platform.setdefault(query["platform"], Counter())
    for key, hit in (("n", 1), ("top1", top1), ("top3", top3), ("displayed", displayed), ("wrong_platform", wrong_platform)):
        total[key] += hit
        counts[key] += hit
    status = "OK  " if top1 else ("TOP3" if top3 else "MISS")
    print(f"{status} {query['id']} [{query['target']:7}] {query['query']!r:42} -> "
          + ", ".join(f"{c[0]}({c[1]})" for c in ranked[:3]))

def summary(c):
    return f"n={c['n']} top1={c['top1']} top3={c['top3']} displayed={c['displayed']} wrong_platform_top1={c['wrong_platform']}"

print(f"\n{args.split}: {summary(total)}")
for platform, counts in sorted(by_platform.items()):
    print(f"  {platform:8} {summary(counts)}")
