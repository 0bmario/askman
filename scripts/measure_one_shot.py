#!/usr/bin/env python3
"""Measure one-shot retrieval-v2 CLI latency at the public query seam.

This harness deliberately starts a fresh process for every sample. It is a
small red-capable regression loop for the one-shot startup regression; it does
not change the frozen evaluation inputs or query behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    # Nearest-rank keeps a small sample conservative: p95 of three values is
    # the maximum, never the middle value that hides a cold launch.
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[min(len(ordered), rank) - 1]


def run_sample(binary: Path, bundle: Path, query: list[str], ort_lib: Path | None) -> dict:
    environment = os.environ.copy()
    if ort_lib is not None:
        environment["DYLD_LIBRARY_PATH"] = str(ort_lib)
    command = [str(binary), "--json", "--bundle", str(bundle), *query]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    stdout = completed.stdout.strip()
    if completed.returncode != 0:
        raise RuntimeError(
            f"query failed with status {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    if not stdout:
        raise RuntimeError("query returned empty stdout")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"query returned non-JSON stdout: {stdout!r}") from error
    result_count = len(payload) if isinstance(payload, list) else len(payload.get("results", []))
    return {
        "elapsed_ms": round(elapsed_ms, 3),
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "result_count": result_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--query", nargs="+", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-p95-ms", type=float, default=126.0)
    parser.add_argument("--ort-lib", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("--runs must be at least 3")
    if not args.binary.is_file():
        parser.error(f"binary does not exist: {args.binary}")
    if not args.bundle.is_dir():
        parser.error(f"bundle does not exist: {args.bundle}")

    samples = [run_sample(args.binary, args.bundle, args.query, args.ort_lib) for _ in range(args.runs)]
    elapsed = [sample["elapsed_ms"] for sample in samples]
    warm_elapsed = elapsed[1:]
    report = {
        "binary": str(args.binary.resolve()),
        "bundle": str(args.bundle.resolve()),
        "query": args.query,
        "runs": args.runs,
        "samples": samples,
        "cold_sample_ms": elapsed[0],
        "warmup_samples_excluded": 1,
        "warm_sample_count": len(warm_elapsed),
        "warm_samples": samples[1:],
        "overall_p50_ms": percentile(elapsed, 0.50),
        "overall_p95_ms": percentile(elapsed, 0.95),
        "warm_p50_ms": percentile(warm_elapsed, 0.50),
        "warm_p95_ms": percentile(warm_elapsed, 0.95),
        "percentile_method": "nearest-rank",
        "max_p95_ms": args.max_p95_ms,
        "passed": percentile(warm_elapsed, 0.95) <= args.max_p95_ms,
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not report["passed"]:
        print(
            f"one-shot warm p95 {report['warm_p95_ms']:.3f}ms exceeds "
            f"{args.max_p95_ms:.3f}ms",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
