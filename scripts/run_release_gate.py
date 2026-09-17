#!/usr/bin/env python3
"""Run the reproducible main-versus-retrieval-v2 release gate.

Builds are isolated and offline. Query processes are run behind the host's
network-deny wrapper. Setup inputs are supplied by the caller and are hashed;
they are never downloaded by this gate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 33_031
MIN_SUCCESS_AT_1_GAIN = 0.05
MAX_REGRESSION = 0.20
FROZEN_MANIFEST_SHA256 = (
    "4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc"
)
FROZEN_DEV_DATASET_SHA256 = (
    "216c0e26f24fda7df197011be4f8add33b6852b7907b32966b0c77e0a26c947d"
)
FROZEN_HOLDOUT_DATASET_SHA256 = (
    "1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418"
)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PEAK_MEMORY_MAC = re.compile(r"maximum resident set size:\s*(\d+)")
PEAK_MEMORY_LINUX = re.compile(
    r"Maximum resident set size \(kbytes\):\s*(\d+)", re.IGNORECASE
)


def load_evaluator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "askman_evaluation_runner", ROOT / "scripts/evaluate_retrieval.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the frozen evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evaluator = load_evaluator()


@dataclass(frozen=True)
class CommandRun:
    displayed_example_ids: tuple[str | None, ...]
    unmapped_results: tuple[dict[str, str], ...]
    displayed_result_count: int
    stdout: str
    stderr: str
    exit_status: int | None
    elapsed_ms: float
    peak_memory_bytes: int | None
    timed_out: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    if not root.is_dir():
        raise ValueError(f"asset directory does not exist: {root}")
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(sha256_file(path).encode())
    return digest.hexdigest()


def file_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def validate_frozen_inputs(
    manifest: Path, dev_dataset: Path, holdout_dataset: Path
) -> None:
    expected = {
        manifest: FROZEN_MANIFEST_SHA256,
        dev_dataset: FROZEN_DEV_DATASET_SHA256,
        holdout_dataset: FROZEN_HOLDOUT_DATASET_SHA256,
    }
    for path, expected_digest in expected.items():
        if not path.is_file():
            raise ValueError(f"frozen evaluation input is missing: {path}")
        actual_digest = sha256_file(path)
        if actual_digest != expected_digest:
            raise ValueError(
                f"frozen evaluation input digest mismatch for {path}: "
                f"expected {expected_digest}, got {actual_digest}"
            )


def run_command(command: Sequence[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        list(command), cwd=cwd, check=False, capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def command_or_none(command: Sequence[str]) -> str | None:
    try:
        return run_command(command)
    except (OSError, RuntimeError):
        return None


def git_revision(repo: Path, ref: str) -> str:
    return run_command(["git", "-C", str(repo), "rev-parse", ref])


def source_lockfile_digest(repo: Path, ref: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:Cargo.lock"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{ref} does not contain Cargo.lock")
    return hashlib.sha256(completed.stdout).hexdigest()


def build_binary(repo: Path, ref: str, label: str, root: Path) -> dict[str, Any]:
    """Build one ref in a disposable worktree and retain only its binary."""
    worktree = root / f"{label}-source"
    target = root / f"{label}-target"
    binary = target / "release" / ("askman.exe" if os.name == "nt" else "askman")
    started = time.perf_counter()
    run_command(["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree), ref])
    try:
        environment = os.environ.copy()
        environment["CARGO_TARGET_DIR"] = str(target)
        completed = subprocess.run(
            ["cargo", "build", "--locked", "--offline", "--release", "--bin", "askman"],
            cwd=worktree,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"{label} build failed ({completed.returncode}):\n"
                f"{completed.stdout}\n{completed.stderr}"
            )
        if not binary.is_file():
            raise RuntimeError(f"{label} build did not produce {binary}")
        return {
            "ref": ref,
            "commit": git_revision(worktree, "HEAD"),
            "cargo_lock_sha256": sha256_file(worktree / "Cargo.lock"),
            "binary_sha256": sha256_file(binary),
            "binary_bytes": binary.stat().st_size,
            "binary": str(binary),
            "build_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "command": [
                "cargo",
                "build",
                "--locked",
                "--offline",
                "--release",
                "--bin",
                "askman",
            ],
        }
    finally:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
            check=False,
            capture_output=True,
            text=True,
        )


def network_wrapper() -> tuple[list[str], str]:
    if platform.system() == "Darwin":
        sandbox = Path("/usr/bin/sandbox-exec")
        if not sandbox.is_file():
            raise RuntimeError("macOS network gate requires /usr/bin/sandbox-exec")
        return [
            str(sandbox),
            "-p",
            "(version 1) (allow default) (deny network*)",
        ], "macOS sandbox-exec deny network*"
    if platform.system() == "Linux":
        unshare = shutil.which("unshare")
        if unshare is None:
            raise RuntimeError("Linux network gate requires unshare")
        return [unshare, "--net", "--"], "Linux unshare --net"
    raise RuntimeError(
        f"no approved query-time network deny wrapper for {platform.system()}"
    )


def time_wrapper() -> tuple[list[str], str]:
    if platform.system() == "Darwin" and Path("/usr/bin/time").is_file():
        return ["/usr/bin/time", "-l"], "macOS time -l"
    time_path = shutil.which("/usr/bin/time") or shutil.which("time")
    if time_path is not None:
        return [time_path, "-v"], "GNU time -v"
    return [], "unavailable"


def peak_memory(stderr: str) -> int | None:
    match = PEAK_MEMORY_MAC.search(stderr)
    if match:
        return int(match.group(1))
    match = PEAK_MEMORY_LINUX.search(stderr)
    if match:
        return int(match.group(1)) * 1024
    return None


def platform_flag(platform_name: str) -> list[str]:
    return {
        "common": [],
        "linux": ["--linux"],
        "osx": ["--osx"],
        "windows": ["--windows"],
    }[platform_name]


def clean_output(value: str) -> str:
    return ANSI_ESCAPE.sub("", value).replace("\r\n", "\n")


def text_output(value: str | bytes | None, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def parse_displayed_results(stdout: str) -> list[dict[str, str]]:
    """Extract every user-visible example description and command pair."""
    lines = dedent(clean_output(stdout)).splitlines()
    results: list[dict[str, str]] = []
    for index, line in enumerate(lines):
        if line.strip() != "Examples:":
            continue
        cursor = index + 1
        while cursor < len(lines):
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            if cursor >= len(lines):
                break
            description_line = lines[cursor]
            if not description_line.startswith("  ") or description_line.startswith("   "):
                break
            description = description_line.strip()
            command_index = cursor + 1
            if command_index >= len(lines) or not lines[command_index].startswith("   "):
                break
            command = lines[command_index].strip()
            if description and command:
                results.append({"description": description, "command": command})
            cursor = command_index + 1
    return results


def example_index(bundle: Path) -> dict[tuple[str, str], tuple[str, ...]]:
    database = bundle / "matching.db"
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """SELECT e.example_id, e.description, e.command
               FROM examples AS e ORDER BY e.example_id"""
        ).fetchall()
    index: dict[tuple[str, str], list[str]] = {}
    for example_id, description, command in rows:
        index.setdefault((description.strip(), command.strip()), []).append(example_id)
    return {key: tuple(value) for key, value in index.items()}


def score_ids(
    task: dict[str, Any],
    displayed_ids: Sequence[str | None],
    *,
    displayed_result_count: int | None = None,
) -> dict[str, Any]:
    acceptable = set(task["acceptable_example_ids"])
    answerable = bool(task["answerable"])
    displayed = list(displayed_ids)
    result_count = len(displayed) if displayed_result_count is None else displayed_result_count
    answered = result_count > 0
    success_at_1 = (
        answerable
        and bool(displayed)
        and displayed[0] is not None
        and displayed[0] in acceptable
    )
    success_at_3 = answerable and bool(
        acceptable.intersection(item for item in displayed[:3] if item is not None)
    )
    return {
        "task_id": task["id"],
        "displayed_example_ids": displayed,
        "displayed_result_count": result_count,
        "answered": answered,
        "success_at_1": success_at_1,
        "success_at_3": success_at_3,
        "incorrect_answer": answerable and answered and not success_at_3,
        "false_answer": not answerable and answered,
    }


def summarize_outcomes(tasks: Sequence[dict[str, Any]], outcomes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if len(tasks) != len(outcomes):
        raise ValueError("task and outcome counts must match")
    answerable = [outcome for task, outcome in zip(tasks, outcomes) if task["answerable"]]
    unanswerable = [outcome for task, outcome in zip(tasks, outcomes) if not task["answerable"]]
    answered_answerable = [outcome for outcome in answerable if outcome["answered"]]

    def pair(count: int, denominator: int) -> dict[str, int]:
        return {"count": count, "denominator": denominator}

    return {
        "tasks": len(tasks),
        "answerable_tasks": len(answerable),
        "unanswerable_tasks": len(unanswerable),
        "success_at_1": pair(sum(outcome["success_at_1"] for outcome in answerable), len(answerable)),
        "success_at_3": pair(sum(outcome["success_at_3"] for outcome in answerable), len(answerable)),
        "coverage": pair(sum(outcome["answered"] for outcome in outcomes), len(outcomes)),
        "incorrect_answered_tasks": pair(
            sum(outcome["incorrect_answer"] for outcome in outcomes), len(answered_answerable)
        ),
        "false_answers_on_unanswerable": pair(
            sum(outcome["false_answer"] for outcome in outcomes), len(unanswerable)
        ),
    }


def breakdown(
    tasks: Sequence[dict[str, Any]], outcomes: Sequence[dict[str, Any]], field: str
) -> dict[str, Any]:
    groups: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for task, outcome in zip(tasks, outcomes):
        name = str(task[field])
        task_group, outcome_group = groups.setdefault(name, ([], []))
        task_group.append(task)
        outcome_group.append(outcome)
    return {
        name: summarize_outcomes(group_tasks, group_outcomes)
        for name, (group_tasks, group_outcomes) in sorted(groups.items())
    }


def failure_examples(
    tasks: Sequence[dict[str, Any]], outcomes: Sequence[dict[str, Any]], limit: int = 10
) -> list[dict[str, Any]]:
    failures = []
    for task, outcome in zip(tasks, outcomes):
        if (task["answerable"] and not outcome["success_at_3"]) or outcome["false_answer"]:
            failures.append(
                {
                    "task_id": task["id"],
                    "family": task["family"],
                    "platform": task["platform"],
                    "question": task["question"],
                    "displayed_example_ids": outcome["displayed_example_ids"],
                    "displayed_result_count": outcome["displayed_result_count"],
                    "incorrect_answer": outcome["incorrect_answer"],
                    "false_answer": outcome["false_answer"],
                }
            )
    return failures[:limit]


def rate(metric: dict[str, int]) -> float:
    denominator = metric["denominator"]
    return metric["count"] / denominator if denominator else 0.0


def paired_bootstrap(
    main_outcomes: Sequence[dict[str, Any]],
    candidate_outcomes: Sequence[dict[str, Any]],
    *,
    seed: int = BOOTSTRAP_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict[str, Any]:
    if len(main_outcomes) != len(candidate_outcomes) or not main_outcomes:
        raise ValueError("paired bootstrap requires equal non-empty outcomes")
    import random

    deltas = [
        int(candidate["success_at_1"]) - int(main["success_at_1"])
        for main, candidate in zip(main_outcomes, candidate_outcomes)
    ]
    generator = random.Random(seed)
    samples = [
        sum(deltas[index] for index in (generator.randrange(len(deltas)) for _ in deltas))
        / len(deltas)
        for _ in range(resamples)
    ]
    samples.sort()

    def nearest_rank(percent: float) -> float:
        index = max(0, min(len(samples) - 1, math.ceil(percent * len(samples)) - 1))
        return samples[index]

    observed = sum(deltas) / len(deltas)
    return {
        "seed": seed,
        "resamples": resamples,
        "paired_task_count": len(deltas),
        "observed_success_at_1_gain": observed,
        "interval_95": {"lower": nearest_rank(0.025), "upper": nearest_rank(0.975)},
        "interval_contains_zero": nearest_rank(0.025) <= 0 <= nearest_rank(0.975),
    }


def compare_quality(
    tasks: Sequence[dict[str, Any]],
    main_outcomes: Sequence[dict[str, Any]],
    candidate_outcomes: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    main = summarize_outcomes(tasks, main_outcomes)
    candidate = summarize_outcomes(tasks, candidate_outcomes)
    families = {}
    for family, main_breakdown in breakdown(tasks, main_outcomes, "family").items():
        candidate_breakdown = breakdown(tasks, candidate_outcomes, "family")[family]
        families[family] = {
            "main": main_breakdown,
            "candidate": candidate_breakdown,
            "success_at_1_gain": rate(candidate_breakdown["success_at_1"])
            - rate(main_breakdown["success_at_1"]),
        }
    platforms = {}
    main_platforms = breakdown(tasks, main_outcomes, "platform")
    candidate_platforms = breakdown(tasks, candidate_outcomes, "platform")
    for platform_name in sorted(main_platforms):
        platforms[platform_name] = {
            "main": main_platforms[platform_name],
            "candidate": candidate_platforms[platform_name],
        }
    return {
        "main": main,
        "candidate": candidate,
        "platform": platforms,
        "family": families,
        "failures": {
            "main": failure_examples(tasks, main_outcomes),
            "candidate": failure_examples(tasks, candidate_outcomes),
        },
    }


def performance_gate(performance: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    main = performance.get("main", {}).get("warmed_query", {})
    candidate = performance.get("candidate", {}).get("warmed_query", {})
    for metric in ("p95_ms", "peak_memory_bytes"):
        main_value = main.get(metric)
        candidate_value = candidate.get(metric)
        if not isinstance(main_value, (int, float)) or not isinstance(
            candidate_value, (int, float)
        ):
            reasons.append(f"warmed-query {metric} is unavailable")
            continue
        if candidate_value > main_value * (1 + MAX_REGRESSION):
            reasons.append(f"warmed-query {metric} regressed by more than 20%")
    return not reasons, reasons


def evaluate_gate(
    quality: dict[str, Any],
    bootstrap: dict[str, Any],
    performance: dict[str, Any],
    execution: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    main = quality["main"]
    candidate = quality["candidate"]
    reasons: list[str] = []
    success_at_1_gain = rate(candidate["success_at_1"]) - rate(main["success_at_1"])
    if success_at_1_gain < MIN_SUCCESS_AT_1_GAIN:
        reasons.append("overall Success@1 gain is below five percentage points")
    positive_families = sum(
        value["success_at_1_gain"] > 0 for value in quality["family"].values()
    )
    if positive_families < 2:
        reasons.append("fewer than two scenario families improved in Success@1")
    regressions = [
        family
        for family, value in quality["family"].items()
        if value["success_at_1_gain"] < 0
    ]
    if regressions:
        reasons.append("Success@1 regressed in: " + ", ".join(regressions))
    for metric in (
        "success_at_3",
        "incorrect_answered_tasks",
        "false_answers_on_unanswerable",
    ):
        main_rate = rate(main[metric])
        candidate_rate = rate(candidate[metric])
        if metric == "success_at_3":
            if candidate_rate < main_rate:
                reasons.append("overall Success@3 regressed")
        elif candidate_rate > main_rate:
            reasons.append(f"overall {metric} regressed")
    for platform_name, value in quality["platform"].items():
        for metric in (
            "success_at_3",
            "incorrect_answered_tasks",
            "false_answers_on_unanswerable",
        ):
            main_rate = rate(value["main"][metric])
            candidate_rate = rate(value["candidate"][metric])
            if metric == "success_at_3" and candidate_rate < main_rate:
                reasons.append(f"{metric} regressed on platform {platform_name}")
            if metric != "success_at_3" and candidate_rate > main_rate:
                reasons.append(f"{metric} regressed on platform {platform_name}")
    if bootstrap["interval_contains_zero"]:
        reasons.append("paired bootstrap interval contains zero")
    performance_passed, performance_reasons = performance_gate(performance)
    reasons.extend(performance_reasons)
    execution = execution or {}
    execution_counts = {
        label: len(failures) for label, failures in execution.items() if failures
    }
    if execution_counts:
        reasons.append(
            "CLI execution failures: "
            + ", ".join(
                f"{label}={count}" for label, count in sorted(execution_counts.items())
            )
        )
    passed = not reasons and performance_passed
    return {
        "passed": passed,
        "decision": "better_askman" if passed else "inconclusive",
        "overall_success_at_1_gain": success_at_1_gain,
        "positive_family_count": positive_families,
        "family_regressions": regressions,
        "reasons": reasons,
        "thresholds": {
            "minimum_success_at_1_gain": MIN_SUCCESS_AT_1_GAIN,
            "maximum_latency_or_memory_regression": MAX_REGRESSION,
        },
    }


def storage_name(bundle_id: str) -> str:
    return "".join(
        chr(byte)
        if chr(byte).isalnum() or chr(byte) in ".-_"
        else f"%{byte:02x}"
        for byte in bundle_id.encode()
    )


def stage_candidate_bundle(bundle: Path, data_dir: Path) -> dict[str, Any]:
    manifest = load_json(bundle / "manifest.json")
    bundle_id = manifest.get("bundle_id")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise ValueError("matching bundle manifest has no bundle_id")
    bundles = data_dir / "bundles"
    bundles.mkdir(parents=True)
    destination = bundles / storage_name(bundle_id)
    shutil.copytree(bundle, destination)
    (data_dir / "active-bundle.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_bundle_id": bundle_id,
                "previous_bundle_id": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "bundle_id": bundle_id,
        "manifest_sha256": sha256_file(bundle / "manifest.json"),
        "bundle_tree_sha256": sha256_tree(bundle),
        "staged_tree_sha256": sha256_tree(data_dir),
    }


def stage_main_data(source: Path, scratch: Path) -> tuple[Path, dict[str, str]]:
    """Copy baseline data into the platform-specific path used by main."""
    home = scratch / "main-home"
    system = platform.system()
    if system == "Darwin":
        data_dir = home / "Library" / "Application Support" / "askman"
        environment = {"HOME": str(home)}
    elif system == "Linux":
        data_root = home / "data"
        data_dir = data_root / "askman"
        environment = {"HOME": str(home), "XDG_DATA_HOME": str(data_root)}
    elif system == "Windows":
        data_root = home / "AppData" / "Roaming"
        data_dir = data_root / "askman"
        environment = {"USERPROFILE": str(home), "APPDATA": str(data_root)}
    else:
        raise RuntimeError(f"unsupported platform for main data staging: {system}")
    shutil.copytree(source, data_dir)
    return data_dir, environment


def map_output_to_ids(
    stdout: str, index: dict[tuple[str, str], tuple[str, ...]]
) -> tuple[tuple[str | None, ...], tuple[dict[str, str], ...]]:
    ids: list[str | None] = []
    unmapped: list[dict[str, str]] = []
    for result in parse_displayed_results(stdout):
        matches = index.get((result["description"], result["command"]), ())
        if matches:
            ids.append(matches[0])
        else:
            ids.append(None)
            unmapped.append(result)
    return tuple(ids), tuple(unmapped)


def run_cli(
    binary: Path,
    data_dir: Path,
    task: dict[str, Any],
    network_prefix: Sequence[str],
    timing_prefix: Sequence[str],
    *,
    index: dict[tuple[str, str], tuple[str, ...]],
    runtime_environment: dict[str, str] | None = None,
) -> CommandRun:
    command = [str(binary), *platform_flag(task["platform"]), *task["question"].split()]
    command = [*timing_prefix, *network_prefix, *command]
    environment = os.environ.copy()
    environment.update(
        {
            "NO_COLOR": "1",
            "CLICOLOR_FORCE": "0",
            "RUST_BACKTRACE": "0",
        }
    )
    if runtime_environment is None:
        environment["ASKMAN_DATA_DIR"] = str(data_dir)
    else:
        environment.pop("ASKMAN_DATA_DIR", None)
        environment.update(runtime_environment)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        timed_out = False
        exit_status: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        exit_status = None
        stdout = text_output(error.stdout)
        stderr = text_output(error.stderr, "timeout")
    elapsed_ms = (time.perf_counter() - started) * 1000
    displayed_ids, unmapped = map_output_to_ids(stdout, index)
    return CommandRun(
        displayed_example_ids=displayed_ids,
        unmapped_results=unmapped,
        displayed_result_count=len(displayed_ids),
        stdout=stdout,
        stderr=stderr,
        exit_status=exit_status,
        elapsed_ms=round(elapsed_ms, 3),
        peak_memory_bytes=peak_memory(stderr),
        timed_out=timed_out,
    )


def run_tasks(
    binary: Path,
    data_dir: Path,
    tasks: Sequence[dict[str, Any]],
    network_prefix: Sequence[str],
    timing_prefix: Sequence[str],
    index: dict[tuple[str, str], tuple[str, ...]],
    runtime_environment: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[CommandRun]]:
    outcomes: list[dict[str, Any]] = []
    runs: list[CommandRun] = []
    for task in tasks:
        result = run_cli(
            binary,
            data_dir,
            task,
            network_prefix,
            timing_prefix,
            index=index,
            runtime_environment=runtime_environment,
        )
        scored = score_ids(
            task,
            result.displayed_example_ids,
            displayed_result_count=result.displayed_result_count,
        )
        scored.update(
            {
                "exit_status": result.exit_status,
                "elapsed_ms": result.elapsed_ms,
                "peak_memory_bytes": result.peak_memory_bytes,
                "unmapped_results": list(result.unmapped_results),
                "stderr": clean_output(result.stderr)[-1000:],
                "timed_out": result.timed_out,
            }
        )
        outcomes.append(scored)
        runs.append(result)
    return outcomes, runs


def latency_summary(runs: Sequence[CommandRun]) -> dict[str, Any]:
    samples = sorted(run.elapsed_ms for run in runs)
    index = max(0, min(len(samples) - 1, math.ceil(len(samples) * 0.95) - 1))
    memory = [run.peak_memory_bytes for run in runs if run.peak_memory_bytes is not None]
    return {
        "sample_count": len(samples),
        "p50_ms": samples[max(0, min(len(samples) - 1, math.ceil(len(samples) * 0.50) - 1))],
        "p95_ms": samples[index],
        "peak_memory_bytes": max(memory) if memory else None,
        "memory_sample_count": len(memory),
    }


def execution_failures(
    tasks: Sequence[dict[str, Any]],
    runs: Sequence[CommandRun],
    phase: str,
) -> list[dict[str, Any]]:
    if len(tasks) != len(runs):
        raise ValueError("task and run counts must match")
    return [
        {
            "phase": phase,
            "task_id": task["id"],
            "exit_status": run.exit_status,
            "timed_out": run.timed_out,
            "stderr": clean_output(run.stderr)[-1000:],
        }
        for task, run in zip(tasks, runs)
        if run.timed_out or run.exit_status != 0
    ]


def warm_latency(
    binary: Path,
    data_dir: Path,
    tasks: Sequence[dict[str, Any]],
    network_prefix: Sequence[str],
    timing_prefix: Sequence[str],
    index: dict[tuple[str, str], tuple[str, ...]],
    warmup_count: int,
    measured_count: int,
    runtime_environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    warmup_tasks = [
        tasks[index_value % len(tasks)] for index_value in range(warmup_count)
    ]
    warmup_runs: list[CommandRun] = []
    for task in warmup_tasks:
        warmup_runs.append(
            run_cli(
                binary,
                data_dir,
                task,
                network_prefix,
                timing_prefix,
                index=index,
                runtime_environment=runtime_environment,
            )
        )
    measured_tasks = [
        tasks[index_value % len(tasks)] for index_value in range(measured_count)
    ]
    runs = [
        run_cli(
            binary,
            data_dir,
            task,
            network_prefix,
            timing_prefix,
            index=index,
            runtime_environment=runtime_environment,
        )
        for task in measured_tasks
    ]
    result = latency_summary(runs)
    result.update(
        {
            "warmup_queries": warmup_count,
            "measured_queries": measured_count,
            "process_scope": "fresh CLI process per sample; filesystem/model cache warmed",
            "execution_failures": execution_failures(
                warmup_tasks, warmup_runs, "warmup"
            )
            + execution_failures(measured_tasks, runs, "measured"),
        }
    )
    return result


def markdown_report(report: dict[str, Any]) -> str:
    gate = report["gate"]
    quality = report["quality"]["combined"]

    def pair(metric: dict[str, int]) -> str:
        return f"{metric['count']}/{metric['denominator']}"

    def memory(value: int | None) -> str:
        return "unavailable" if value is None else f"{value:,} B"

    lines = [
        "# Askman release gate",
        "",
        f"Decision: **{gate['decision']}**",
        "",
        "## Inputs and builds",
        "",
        f"- Generated: `{report['generated_at_utc']}`",
        f"- Query network policy: `{report['protocol']['query_network_policy']}`",
        f"- Reproduction: `{report['reproduction_command']}`",
        f"- Freeze: `{report['inputs']['freeze_id']}`",
        f"- Main commit: `{report['builds']['main']['commit']}`",
        f"- Main Cargo.lock SHA-256: `{report['builds']['main']['cargo_lock_sha256']}`",
        f"- Main binary SHA-256: `{report['builds']['main']['binary_sha256']}`",
        f"- Candidate commit: `{report['builds']['candidate']['commit']}`",
        f"- Candidate Cargo.lock SHA-256: `{report['builds']['candidate']['cargo_lock_sha256']}`",
        f"- Candidate binary SHA-256: `{report['builds']['candidate']['binary_sha256']}`",
        f"- Freeze manifest SHA-256: `{report['inputs']['freeze_manifest_sha256']}`",
        f"- Candidate bundle: `{report['inputs']['bundle']['bundle_id']}`",
        f"- Candidate bundle tree SHA-256: `{report['inputs']['bundle']['bundle_tree_sha256']}`",
        f"- Main data tree SHA-256: `{report['inputs']['main_data_dir_tree_sha256']}`",
        f"- Dev dataset SHA-256: `{report['inputs']['dev_dataset_sha256']}`",
        f"- Holdout dataset SHA-256: `{report['inputs']['holdout_dataset_sha256']}`",
        f"- Scorer SHA-256: `{report['inputs']['scorer_sha256']}`",
        "- Per-file input digests: recorded in the machine-readable report.",
        "",
        "## User-visible quality",
        "",
        "| Metric | main | retrieval-v2 |",
        "| --- | ---: | ---: |",
    ]
    metric_labels = {
        "success_at_1": "Success@1",
        "success_at_3": "Success@3",
        "coverage": "Coverage",
        "incorrect_answered_tasks": "Incorrect answered",
        "false_answers_on_unanswerable": "False answers",
    }
    for metric in (
        "success_at_1",
        "success_at_3",
        "coverage",
        "incorrect_answered_tasks",
        "false_answers_on_unanswerable",
    ):
        main_metric = quality["main"][metric]
        candidate_metric = quality["candidate"][metric]
        lines.append(
            f"| {metric_labels[metric]} | {pair(main_metric)} | {pair(candidate_metric)} |"
        )
    lines.extend(
        [
            "",
            "## Platform breakdown",
            "",
            "| Platform | main Success@1 | retrieval-v2 Success@1 | main Success@3 | retrieval-v2 Success@3 | main false answers | retrieval-v2 false answers |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for platform_name, value in quality["platform"].items():
        lines.append(
            f"| {platform_name} | {pair(value['main']['success_at_1'])} | "
            f"{pair(value['candidate']['success_at_1'])} | "
            f"{pair(value['main']['success_at_3'])} | "
            f"{pair(value['candidate']['success_at_3'])} | "
            f"{pair(value['main']['false_answers_on_unanswerable'])} | "
            f"{pair(value['candidate']['false_answers_on_unanswerable'])} |"
        )
    lines.extend(
        [
            "",
            "## Scenario-family breakdown",
            "",
            "| Family | main Success@1 | retrieval-v2 Success@1 | gain | main incorrect | retrieval-v2 incorrect |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for family, value in quality["family"].items():
        lines.append(
            f"| {family} | {pair(value['main']['success_at_1'])} | "
            f"{pair(value['candidate']['success_at_1'])} | "
            f"{value['success_at_1_gain']:.4f} | "
            f"{pair(value['main']['incorrect_answered_tasks'])} | "
            f"{pair(value['candidate']['incorrect_answered_tasks'])} |"
        )
    lines.extend(
        [
            "",
            "## Performance",
            "",
            "| Phase | main p95 | retrieval-v2 p95 | main peak memory | retrieval-v2 peak memory |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for split_name in ("dev", "holdout"):
        main_fresh = report["performance"]["main"][split_name]["fresh_process"]
        candidate_fresh = report["performance"]["candidate"][split_name]["fresh_process"]
        lines.append(
            f"| {split_name} fresh | {main_fresh['p95_ms']:.3f} ms | "
            f"{candidate_fresh['p95_ms']:.3f} ms | "
            f"{memory(main_fresh['peak_memory_bytes'])} | "
            f"{memory(candidate_fresh['peak_memory_bytes'])} |"
        )
    main_warm = report["performance"]["main"]["warmed_query"]
    candidate_warm = report["performance"]["candidate"]["warmed_query"]
    lines.append(
        f"| warmed query | {main_warm['p95_ms']:.3f} ms | "
        f"{candidate_warm['p95_ms']:.3f} ms | "
        f"{memory(main_warm['peak_memory_bytes'])} | "
        f"{memory(candidate_warm['peak_memory_bytes'])} |"
    )
    lines.extend(
        [
            "",
            "## Execution",
            "",
            f"- Main failed CLI runs: `{len(report['execution']['main'])}`.",
            f"- Candidate failed CLI runs: `{len(report['execution']['candidate'])}`.",
            "",
            "## Failure examples",
            "",
        ]
    )
    for label in ("main", "candidate"):
        lines.append(f"### {label}")
        failures = quality["failures"][label]
        if not failures:
            lines.append("- None recorded.")
            continue
        lines.extend(
            f"- `{failure['task_id']}` ({failure['family']}/{failure['platform']}), "
            f"displayed IDs: `{', '.join(item or 'unmapped' for item in failure['displayed_example_ids']) or 'none'}`."
            for failure in failures
        )
    lines.extend(
        [
            "",
            "## Paired bootstrap",
            "",
            f"- Observed Success@1 gain: `{report['bootstrap']['observed_success_at_1_gain']:.4f}`.",
            f"- {report['bootstrap']['resamples']:,} resamples; seed `{report['bootstrap']['seed']}`.",
            f"- 95% interval: `{report['bootstrap']['interval_95']['lower']:.4f}` to "
            f"`{report['bootstrap']['interval_95']['upper']:.4f}`.",
            "",
            "## Gate conditions",
            "",
        ]
    )
    if gate["reasons"]:
        lines.extend(f"- {reason}" for reason in gate["reasons"])
    else:
        lines.append("- All ADR-0001 conditions passed.")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in report["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", type=Path, default=ROOT)
    result.add_argument("--main-ref", default="main")
    result.add_argument("--candidate-ref", default="origin/retrieval-v2")
    result.add_argument(
        "--freeze-manifest",
        type=Path,
        default=ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json",
    )
    result.add_argument("--main-data-dir", type=Path, required=True)
    result.add_argument("--bundle", type=Path, required=True)
    result.add_argument(
        "--dev-dataset",
        type=Path,
        default=ROOT / "tests/fixtures/evaluation/frozen-dev-v2-expanded.json",
    )
    result.add_argument(
        "--allow-holdout",
        action="store_true",
        help="authorize reading the frozen holdout split",
    )
    result.add_argument(
        "--holdout-dataset",
        type=Path,
        default=ROOT / "tests/fixtures/evaluation/frozen-holdout-v2-expanded.json",
    )
    result.add_argument("--warmup-queries", type=int, default=5)
    result.add_argument("--warm-queries", type=int, default=30)
    result.add_argument("--output-json", type=Path, required=True)
    result.add_argument("--output-markdown", type=Path, required=True)
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo_root.resolve()
    bundle = args.bundle.resolve()
    main_data_dir = args.main_data_dir.resolve()
    freeze_manifest = args.freeze_manifest.resolve()
    if not args.allow_holdout:
        raise ValueError("--allow-holdout is required for the release gate")
    validate_frozen_inputs(freeze_manifest, args.dev_dataset.resolve(), args.holdout_dataset.resolve())
    if not bundle.is_dir() or not (bundle / "manifest.json").is_file():
        raise ValueError("--bundle must be a validated matching bundle directory")
    if not main_data_dir.is_dir():
        raise ValueError("--main-data-dir must be a provisioned main CLI data directory")
    if not (main_data_dir / "commands.db").is_file():
        raise ValueError("--main-data-dir must contain commands.db")
    if not (main_data_dir / "models").is_dir():
        raise ValueError("--main-data-dir must contain the pinned models directory")
    if args.warmup_queries <= 0 or args.warm_queries <= 0:
        raise ValueError("warmup and measured query counts must be positive")

    freeze = load_json(freeze_manifest)
    dev = load_json(args.dev_dataset)
    holdout = load_json(args.holdout_dataset)
    evaluator.validate_dataset_pair(dev, holdout)
    if freeze.get("benchmark_id") != "askman-evaluation-v2":
        raise ValueError("freeze manifest is not the frozen evaluation-v2 manifest")
    if freeze.get("splits", {}).get("dev", {}).get("sha256") != FROZEN_DEV_DATASET_SHA256:
        raise ValueError("freeze manifest dev split digest is not the frozen value")
    if freeze.get("splits", {}).get("holdout", {}).get("sha256") != FROZEN_HOLDOUT_DATASET_SHA256:
        raise ValueError("freeze manifest holdout split digest is not the frozen value")
    index = example_index(bundle)
    network_prefix, network_policy = network_wrapper()
    timing_prefix, timing_policy = time_wrapper()

    with tempfile.TemporaryDirectory(prefix="askman-release-gate-") as directory:
        scratch = Path(directory)
        builds = {
            "main": build_binary(repo, args.main_ref, "main", scratch),
            "candidate": build_binary(repo, args.candidate_ref, "candidate", scratch),
        }
        candidate_data_dir = scratch / "candidate-data"
        candidate_data_dir.mkdir()
        bundle_input = stage_candidate_bundle(bundle, candidate_data_dir)
        main_data_runtime_dir, main_runtime_environment = stage_main_data(
            main_data_dir, scratch
        )
        candidate_runtime_environment = {"ASKMAN_DATA_DIR": str(candidate_data_dir)}
        quality: dict[str, Any] = {}
        all_main_outcomes: list[dict[str, Any]] = []
        all_candidate_outcomes: list[dict[str, Any]] = []
        all_tasks: list[dict[str, Any]] = []
        performance: dict[str, Any] = {"main": {}, "candidate": {}}
        execution: dict[str, list[dict[str, Any]]] = {"main": [], "candidate": []}
        for split_name, dataset in (("dev", dev), ("holdout", holdout)):
            tasks = dataset["tasks"]
            main_outcomes, main_runs = run_tasks(
                Path(builds["main"]["binary"]),
                main_data_runtime_dir,
                tasks,
                network_prefix,
                timing_prefix,
                index,
                runtime_environment=main_runtime_environment,
            )
            candidate_outcomes, candidate_runs = run_tasks(
                Path(builds["candidate"]["binary"]),
                candidate_data_dir,
                tasks,
                network_prefix,
                timing_prefix,
                index,
                runtime_environment=candidate_runtime_environment,
            )
            quality[split_name] = compare_quality(tasks, main_outcomes, candidate_outcomes)
            all_tasks.extend(tasks)
            all_main_outcomes.extend(main_outcomes)
            all_candidate_outcomes.extend(candidate_outcomes)
            execution["main"].extend(
                execution_failures(tasks, main_runs, f"{split_name}:fresh")
            )
            execution["candidate"].extend(
                execution_failures(tasks, candidate_runs, f"{split_name}:fresh")
            )
            performance["main"][split_name] = {"fresh_process": latency_summary(main_runs)}
            performance["candidate"][split_name] = {"fresh_process": latency_summary(candidate_runs)}

        performance["main"]["warmed_query"] = warm_latency(
            Path(builds["main"]["binary"]),
            main_data_runtime_dir,
            all_tasks,
            network_prefix,
            timing_prefix,
            index,
            args.warmup_queries,
            args.warm_queries,
            runtime_environment=main_runtime_environment,
        )
        performance["candidate"]["warmed_query"] = warm_latency(
            Path(builds["candidate"]["binary"]),
            candidate_data_dir,
            all_tasks,
            network_prefix,
            timing_prefix,
            index,
            args.warmup_queries,
            args.warm_queries,
            runtime_environment=candidate_runtime_environment,
        )
        execution["main"].extend(performance["main"]["warmed_query"]["execution_failures"])
        execution["candidate"].extend(
            performance["candidate"]["warmed_query"]["execution_failures"]
        )

        combined = compare_quality(all_tasks, all_main_outcomes, all_candidate_outcomes)
        answerable_pairs = [
            (main, candidate)
            for task, main, candidate in zip(
                all_tasks, all_main_outcomes, all_candidate_outcomes
            )
            if task["answerable"]
        ]
        bootstrap = paired_bootstrap(
            [main for main, _ in answerable_pairs],
            [candidate for _, candidate in answerable_pairs],
        )
        gate = evaluate_gate(combined, bootstrap, performance, execution)
        report = {
            "schema_version": 1,
            "evidence_id": "askman-main-vs-retrieval-v2-v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "complete",
            "protocol": {
                "primary_outcome": "user-visible displayed example IDs and abstentions",
                "development_and_holdout": True,
                "no_holdout_tuning": True,
                "query_network_policy": network_policy,
                "timing_policy": timing_policy,
                "setup_download_separate": True,
                "main_ref": args.main_ref,
                "candidate_ref": args.candidate_ref,
                "holdout_access_authorized": args.allow_holdout,
            },
            "inputs": {
                "benchmark_id": freeze["benchmark_id"],
                "freeze_id": freeze["freeze_id"],
                "freeze_manifest_sha256": sha256_file(freeze_manifest),
                "bundle": bundle_input,
                "main_data_dir_tree_sha256": sha256_tree(main_data_dir),
                "main_data_file_sha256": file_digests(main_data_dir),
                "bundle_file_sha256": file_digests(bundle),
                "dev_dataset_sha256": sha256_file(args.dev_dataset),
                "holdout_dataset_sha256": sha256_file(args.holdout_dataset),
                "scorer_sha256": sha256_file(ROOT / "scripts/evaluate_retrieval.py"),
            },
            "builds": builds,
            "quality": {**quality, "combined": combined},
            "bootstrap": bootstrap,
            "performance": performance,
            "execution": execution,
            "gate": gate,
            "recommendation": gate["decision"],
            "reproduction_command": " ".join(sys.argv),
            "limitations": [
                "The main CLI requires a separately provisioned commands.db and model cache; their tree digest is recorded and setup/download is outside this gate.",
                "Warmed-query samples use fresh CLI processes after filesystem/model caches are warmed; the CLI has no persistent query-server mode.",
                "Example IDs are mapped from user-visible description/command pairs in the pinned candidate bundle; unmapped output is conservatively scored as not acceptable.",
                "Peak memory depends on the host time implementation; missing samples make the performance gate inconclusive.",
            ],
            "host": {
                "platform": platform.platform(),
                "python": sys.version,
                "rustc": command_or_none(["rustc", "--version"]),
                "cargo": command_or_none(["cargo", "--version"]),
                "logical_cpus": os.cpu_count(),
            },
        }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_markdown.write_text(markdown_report(report), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run(args)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, sqlite3.Error) as error:
        print(f"release gate failed: {error}", file=sys.stderr)
        return 2
    print(f"wrote {args.output_json} and {args.output_markdown}: {report['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
