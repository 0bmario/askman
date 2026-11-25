"""Harness for examples/startup_bench.rs (startup-bench experiment, scratch).

  python3 startup_bench.py vectors <bin> <home> <variant>...        max cosine diff vs v0, 20 dev queries
  python3 startup_bench.py time <bin> <home> <n> <variant>...       interleaved fresh-process timing

`time` runs n iterations over 5 dev queries (n*5 samples per variant), alternating variant order
every iteration, one fresh process per sample. Prints p50/p95 per stage and RAW lines.
"""
import json, math, os, subprocess, sys, time
from pathlib import Path

EVAL = Path(__file__).resolve().parent.parent / "eval" / "askman-eval-v2.json"
DEV = [q for q in json.load(open(EVAL))["queries"] if q["split"] == "dev"]


def env_for(home):
    return dict(os.environ, HOME=home, NO_COLOR="1")


def vectors(binary, home, variants):
    queries = [q["query"] for q in DEV[:20]]
    def run(variant):
        out = subprocess.run([binary, "vectors", variant], input="\n".join(queries) + "\n",
                             capture_output=True, text=True, check=True, env=env_for(home)).stdout
        return [[float(x) for x in line.split()] for line in out.splitlines()]
    base = run("v0")
    for variant in variants:
        rows = run(variant)
        cos_diffs, abs_diffs = [], []
        for a, b in zip(base, rows):
            dot = sum(x * y for x, y in zip(a, b))
            norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
            cos_diffs.append(1 - dot / norm)
            abs_diffs.append(max(abs(x - y) for x, y in zip(a, b)))
        assert len(rows) == len(base) == 20
        print(f"{variant:6} n={len(rows)} max(1-cos)={max(cos_diffs):.3e} max|dx|={max(abs_diffs):.3e}")


COLS = ("premain", "db", "tokenizer", "session", "embed", "knn", "in_main", "exit", "wall")


def time_variants(binary, home, n, variants):
    queries = [(q["target"], q["query"]) for q in DEV[:5]]
    def run(variant, target, query):
        spawn_ns = time.time_ns()
        start = time.perf_counter()
        out = subprocess.run([binary, "time", variant, target, *query.split()], capture_output=True,
                             text=True, check=True, env=env_for(home)).stdout.split()
        wall = (time.perf_counter() - start) * 1000
        main_ns, db, tok, sess, emb, knn, total = int(out[0]), *map(float, out[1:7])
        premain = (main_ns - spawn_ns) / 1e6
        return premain, db, tok, sess, emb, knn, total, wall - premain - total, wall
    for variant in variants:  # warm-up: page cache, dyld cache
        for target, query in queries:
            run(variant, target, query)
    samples = {v: [] for v in variants}
    for i in range(n):
        for target, query in queries:
            for variant in (variants if i % 2 == 0 else variants[::-1]):
                samples[variant].append(run(variant, target, query))
    def pct(values, p):
        values = sorted(v for v in values if not math.isnan(v))
        return values[max(int(len(values) * p) - 1, 0)] if values else float("nan")
    for variant, rows in samples.items():
        cols = list(zip(*rows))
        print(f"{variant:6} n={len(rows)} " + "  ".join(
            f"{name} {pct(c, .5):.1f}/{pct(c, .95):.1f}" for name, c in zip(COLS, cols)))
    print("# columns are p50/p95 ms; RAW:", *COLS)
    for variant, rows in samples.items():
        for row in rows:
            print("RAW", variant, *(f"{x:.3f}" for x in row), sep="\t")


if __name__ == "__main__":
    mode, binary, home = sys.argv[1:4]
    if mode == "vectors":
        vectors(binary, home, sys.argv[4:])
    else:
        time_variants(binary, home, int(sys.argv[4]), sys.argv[5:])
