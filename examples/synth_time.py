"""Stage-0 timing for examples/synth_rank.rs (synth-index, scratch).

  python3 examples/synth_time.py <synth_rank bin> <home> <n>

One fresh process per sample over the first n dev queries; prints p50/p95 ms of each stage and RAW lines.
"""
import json, os, subprocess, sys
from pathlib import Path

binary, home, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
doc = json.load(open(Path(__file__).resolve().parent.parent / "eval" / "askman-eval-v3.json"))
dev = [q for q in doc["queries"] if q["split"] == "dev"][:n]
env = dict(os.environ, HOME=home)
subprocess.run([binary, "time", dev[0]["target"], *dev[0]["query"].split()], env=env, check=True, capture_output=True)  # warm-up
rows = []
for q in dev:
    out = subprocess.run([binary, "time", q["target"], *q["query"].split()], env=env, check=True,
                         capture_output=True, text=True).stdout.split()
    rows.append([float(x) for x in out[:4]] + [int(out[4]), int(out[5])])
def pct(values, p):
    values = sorted(values)
    return values[max(int(len(values) * p) - 1, 0)]
cols = list(zip(*rows))
for name, col in zip(("init", "embed", "knn1+rules", "knn2"), cols):
    print(f"{name:11} p50 {pct(col, .5):6.2f}  p95 {pct(col, .95):6.2f}  mean {sum(col) / len(col):6.2f}")
print(f"n={len(rows)}; knn2 rows per query: min {min(cols[5])} max {max(cols[5])}")
for q, r in zip(dev, rows):
    print("RAW", q["id"], *r, sep="\t")
