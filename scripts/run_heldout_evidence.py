#!/usr/bin/env python3
"""Run the frozen hybrid holdout evidence protocol.

This is a local, offline evidence runner.  It delegates scoring to the frozen
evaluation runner and never executes a returned command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as host_platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SCHEMA_VERSION = 1
EXPECTED_HOLDOUT_TASKS = 30
FROZEN_HOLDOUT_DATASET_SHA256 = (
    "ddd20209e2426afe6b3122ab43b953822e8a1c2e70b147045930558345bee320"
)
# Updated when the committed evidence protocol changes.
FROZEN_EVIDENCE_CONFIG_SHA256 = (
    "67686420b06fe4f24ed88567854847ea497de6f5d39d009bfb6e20a1b3d78ff3"
)
MODEL_REPO = "Qdrant/all-MiniLM-L6-v2-onnx"
MODEL_REVISION = "5f1b8cd78bc4fb444dd171e59b18f3a3af89a079"
RUNTIME_VERSION = "1.20.0"
MODEL_FILES = (
    "model.onnx",
    "config.json",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "tokenizer.json",
)


def load_evaluator_module() -> Any:
    import importlib.util

    path = ROOT / "scripts/evaluate_retrieval.py"
    spec = importlib.util.spec_from_file_location("askman_evaluation_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load evaluator module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evaluator = load_evaluator_module()


def percentile(values: Iterable[float], percent: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    # Nearest-rank percentile.  With five runs p95 is the maximum, explicitly.
    rank = max(1, int((len(ordered) * percent) + 0.999999))
    return round(ordered[min(rank, len(ordered)) - 1], 3)


def summarize_samples(values: Iterable[float]) -> dict[str, Any]:
    samples = list(values)
    return {
        "count": len(samples),
        "p50_ms": percentile(samples, 0.50),
        "p95_ms": percentile(samples, 0.95),
        "samples_ms": [round(value, 3) for value in samples],
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def load_evidence_config(path: Path) -> dict[str, Any]:
    config = load_json(path)
    if config.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported heldout evidence config schema")
    if config.get("split") != "holdout":
        raise ValueError("heldout evidence config must use the holdout split")
    if config.get("dataset_sha256") != FROZEN_HOLDOUT_DATASET_SHA256:
        raise ValueError("heldout evidence config must pin the committed holdout dataset")
    quality = config.get("quality")
    if not isinstance(quality, dict):
        raise ValueError("heldout evidence config quality must be an object")
    if quality.get("retrievers") != ["keyword", "hybrid"]:
        raise ValueError("heldout evidence must compare keyword and hybrid")
    if quality.get("runs_per_retriever") != 1:
        raise ValueError("heldout quality must run each retriever exactly once")
    if quality.get("no_holdout_tuning_or_rerun") is not True:
        raise ValueError("heldout evidence must forbid tuning and reruns")
    performance = config.get("performance")
    if not isinstance(performance, dict):
        raise ValueError("heldout evidence config performance must be an object")
    for name in ("fresh_process_runs", "warmup_queries", "warm_queries"):
        value = performance.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"heldout performance {name} must be positive")
    if config.get("execution_provider") != "CPU only; no GPU":
        raise ValueError("heldout evidence must use the CPU-only provider")
    return config


def parse_key_value_output(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    result: dict[str, Any] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            key, separator, value = line.rstrip("\n").partition("=")
            if not separator:
                continue
            if re.fullmatch(r"[0-9]+", value):
                result[key] = int(value)
            else:
                result[key] = value
    return result


def require_build_metadata(path: Path | None, label: str) -> dict[str, Any]:
    metadata = parse_key_value_output(path)
    required_keys = {"build_time_ms", "artifact_size_bytes", "peak_memory_bytes"}
    missing_keys = sorted(required_keys - metadata.keys())
    if missing_keys:
        raise ValueError(
            f"{label} build metadata is missing: {', '.join(missing_keys)}"
        )
    return metadata


def run_command(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def host_value(command: list[str], fallback: str | None = None) -> str | None:
    return run_command(command) or fallback


def read_ram_bytes() -> int | None:
    value = host_value(["sysctl", "-n", "hw.memsize"])
    if value and value.isdigit():
        return int(value)
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def power_state() -> dict[str, Any]:
    state: dict[str, Any] = {"policy": "record-only; no power settings changed"}
    for name, command in (
        ("battery", ["pmset", "-g", "batt"]),
        ("thermal", ["pmset", "-g", "therm"]),
    ):
        value = run_command(command)
        if value is not None:
            state[name] = value
    return state


def host_metadata(config: dict[str, Any]) -> dict[str, Any]:
    environment = {
        key: os.environ[key]
        for key in ("RAYON_NUM_THREADS", "OMP_NUM_THREADS", "TOKENIZERS_PARALLELISM")
        if key in os.environ
    }
    threading = dict(config["performance"]["threading"])
    threading.update(
        {
            "available_parallelism": os.cpu_count(),
            "environment_overrides": environment,
            "effective_ort_thread_count": "not instrumented; default available parallelism",
        }
    )
    return {
        "cpu": {
            "model": host_value(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                host_platform.processor() or None,
            ),
            "logical_count": os.cpu_count(),
        },
        "ram_bytes": read_ram_bytes(),
        "os": {
            "system": host_platform.system(),
            "release": host_platform.release(),
            "version": host_platform.version(),
            "machine": host_platform.machine(),
            "sw_vers": host_value(["sw_vers", "-productVersion"]),
        },
        "threading": threading,
        "power": power_state(),
    }


def dependency_versions() -> dict[str, str | None]:
    lockfile = ROOT / "Cargo.lock"
    text = lockfile.read_text(encoding="utf-8")
    versions: dict[str, str | None] = {}
    for name in ("fastembed", "sqlite-vec", "rusqlite", "ort", "ort-sys"):
        match = re.search(
            rf'\[\[package\]\]\s+name = "{re.escape(name)}"\s+version = "([^"]+)"',
            text,
        )
        versions[name] = match.group(1) if match else None
    versions["rustc"] = run_command(["rustc", "--version"])
    versions["cargo"] = run_command(["cargo", "--version"])
    return versions


def model_digests(model_cache: Path) -> dict[str, str | None]:
    snapshot = model_cache / "models--Qdrant--all-MiniLM-L6-v2-onnx" / "snapshots" / MODEL_REVISION
    return {
        name: sha256_file(snapshot / name) if (snapshot / name).is_file() else None
        for name in MODEL_FILES
    }


def query_tasks(dataset: dict[str, Any]) -> list[dict[str, str]]:
    tasks = dataset.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != EXPECTED_HOLDOUT_TASKS:
        raise ValueError("heldout evidence requires the 30-task holdout dataset")
    return [{"task_id": task["id"], "question": task["question"], "platform": task["platform"]} for task in tasks]


def run_quality(
    args: argparse.Namespace, retriever: str, hybrid_config: Path | None
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts/evaluate_retrieval.py"),
        "--artifact",
        str(args.artifact),
        "--manifest",
        str(args.manifest),
        "--dataset",
        str(args.dataset),
        "--split",
        "holdout",
        "--allow-holdout",
        "--retriever",
        retriever,
    ]
    if retriever == "hybrid":
        command.extend(
            [
                "--hybrid-config",
                str(hybrid_config),
                "--dense-helper",
                str(args.dense_helper),
                "--model-cache",
                str(args.model_cache),
            ]
        )
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{retriever} holdout evaluation failed: {completed.stderr.strip()}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{retriever} evaluator returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{retriever} evaluator returned a non-object report")
    return value


def run_hybrid_query(
    connection: Any,
    client: Any,
    task: dict[str, str],
    candidate: Any,
) -> None:
    keyword_candidates = evaluator.fetch_candidates(
        connection,
        task["question"],
        task["platform"],
        candidate.keyword_budget,
    )
    dense_candidates = client.query(
        task["question"],
        task["platform"],
        candidate.dense_budget,
    )
    fused_candidates = evaluator.fuse_candidates(
        keyword_candidates,
        dense_candidates,
        candidate,
    )
    evaluator.hybrid_results(fused_candidates, candidate)


def run_hybrid_queries(
    helper: Path,
    artifact: Path,
    model_cache: Path,
    tasks: list[dict[str, str]],
    warmup_count: int,
    measured_count: int,
    candidate: Any,
) -> dict[str, Any]:
    import sqlite3

    with sqlite3.connect(artifact) as connection:
        client = evaluator.DenseClient(helper, artifact, model_cache)
        try:
            for index in range(warmup_count):
                run_hybrid_query(connection, client, tasks[index % len(tasks)], candidate)
            measured: list[float] = []
            for index in range(measured_count):
                task = tasks[index % len(tasks)]
                before = time.perf_counter()
                run_hybrid_query(connection, client, task, candidate)
                measured.append((time.perf_counter() - before) * 1000)
            return {
                "query": summarize_samples(measured),
                "startup": round(client.startup_ms, 3),
                "model_load_ms": client.model_load_ms,
                "peak_memory_bytes": client.peak_memory_bytes,
            }
        finally:
            client.close()


def run_fresh_performance_process(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts/run_heldout_evidence.py"),
        "--performance-worker",
        "--artifact",
        str(args.artifact),
        "--manifest",
        str(args.manifest),
        "--dataset",
        str(args.dataset),
        "--hybrid-config",
        str(args.hybrid_config),
        "--evidence-config",
        str(args.evidence_config),
        "--dense-helper",
        str(args.dense_helper),
        "--model-cache",
        str(args.model_cache),
        "--build-metadata",
        str(args.build_metadata),
        "--dense-build-metadata",
        str(args.dense_build_metadata),
        "--network-probe",
        str(args.network_probe),
        "--output",
        "/dev/null",
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if completed.returncode != 0:
        raise RuntimeError(
            f"fresh performance process failed: {completed.stderr.strip()}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("fresh performance process returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError("fresh performance process returned a non-object report")
    value["runner_process_elapsed_ms"] = round(elapsed_ms, 3)
    return value


def performance_report(
    args: argparse.Namespace,
    config: dict[str, Any],
    tasks: list[dict[str, str]],
    candidate: Any,
) -> dict[str, Any]:
    performance = config["performance"]
    fresh_runs: list[dict[str, Any]] = []
    for _ in range(performance["fresh_process_runs"]):
        fresh_runs.append(
            run_fresh_performance_process(args)
        )
    warm = run_hybrid_queries(
        args.dense_helper,
        args.artifact,
        args.model_cache,
        tasks,
        performance["warmup_queries"],
        performance["warm_queries"],
        candidate,
    )
    return {
        "workload": performance["workload"],
        "query_scope": "selected hybrid end-to-end: FTS5, dense helper, RRF, and weak-match cutoff",
        "fresh_process": {
            "run_count": len(fresh_runs),
            "process_scope": "fresh evidence-runner process and fresh dense helper process",
            "warmup_query_count_per_run": performance["warmup_queries"],
            "measured_query_count_per_run": performance["warm_queries"],
            "initialization_ms": summarize_samples(run["startup"] for run in fresh_runs),
            "model_load_ms": summarize_samples(run["model_load_ms"] for run in fresh_runs if run["model_load_ms"] is not None),
            "query": summarize_samples(value for run in fresh_runs for value in run["query"]["samples_ms"]),
            "runner_process_elapsed_ms": summarize_samples(
                run["runner_process_elapsed_ms"] for run in fresh_runs
            ),
            "peak_memory_bytes": {
                "max": max((run["peak_memory_bytes"] or 0) for run in fresh_runs),
                "samples": [run["peak_memory_bytes"] for run in fresh_runs],
            },
        },
        "warm_in_process": {
            "process_count": 1,
            "warmup_query_count": performance["warmup_queries"],
            "measured_query_count": performance["warm_queries"],
            "initialization_ms": warm["startup"],
            "model_load_ms": warm["model_load_ms"],
            "query": warm["query"],
            "peak_memory_bytes": warm["peak_memory_bytes"],
        },
    }


def deterministic_invariants(artifact: Path) -> dict[str, Any]:
    import sqlite3

    def deterministic_id(kind: str, fields: Iterable[str]) -> str:
        digest = hashlib.sha256()
        digest.update(b"askman-tldr-subset-id-v1\n")
        digest.update(kind.encode())
        digest.update(b"\0")
        for field in fields:
            encoded = field.encode()
            digest.update(str(len(encoded)).encode())
            digest.update(b"\0")
            digest.update(encoded)
            digest.update(b"\0")
        return f"{kind}-{digest.hexdigest()}"

    with sqlite3.connect(artifact) as connection:
        rows = list(
            connection.execute(
                """SELECT page_id, page_name, source_path, source_revision,
                          source_ref, platform, language, page_kind
                   FROM pages ORDER BY page_position"""
            )
        )
        grouped: dict[str, dict[str, str]] = {}
        page_ids = {row[0] for row in rows}
        page_identity_errors = 0
        for (
            page_id,
            page_name,
            source_path,
            source_revision,
            source_ref,
            platform,
            language,
            _,
        ) in rows:
            grouped.setdefault(page_name, {})[platform] = page_id
            expected_page_id = deterministic_id(
                "page", [source_revision, source_path, platform, language]
            )
            expected_source_ref = f"tldr-pages@{source_revision}:{source_path}"
            has_page_id_mismatch = page_id != expected_page_id
            has_source_ref_mismatch = source_ref != expected_source_ref
            has_unsupported_platform = platform not in evaluator.SUPPORTED_PLATFORMS
            has_missing_language = not language
            has_page_identity_error = any(
                (
                    has_page_id_mismatch,
                    has_source_ref_mismatch,
                    has_unsupported_platform,
                    has_missing_language,
                )
            )
            if has_page_identity_error:
                page_identity_errors += 1
        duplicate_page_ids = len(rows) - len(page_ids)
        page_source_keys = {(row[2], row[5], row[6]) for row in rows}
        duplicate_page_source_keys = len(rows) - len(page_source_keys)
        duplicate_page_variants = len(rows) - len(
            {(row[1], row[5]) for row in rows}
        )

        examples = list(
            connection.execute(
                "SELECT example_id, page_id, position FROM examples ORDER BY example_id"
            )
        )
        example_identity_errors = 0
        orphan_examples = 0
        for example_id, page_id, position in examples:
            is_orphan = page_id not in page_ids
            expected_example_id = deterministic_id(
                "example", [page_id, str(position)]
            )
            if is_orphan:
                orphan_examples += 1
            if is_orphan or example_id != expected_example_id or position <= 0:
                example_identity_errors += 1

        precedence: dict[str, dict[str, str]] = {}
        precedence_deterministic: dict[str, bool] = {}
        for platform in sorted(evaluator.SUPPORTED_PLATFORMS):
            selected = evaluator.selected_page_ids(connection, platform)
            repeated = evaluator.selected_page_ids(connection, platform)
            expected: dict[str, str] = {}
            for name, variants in grouped.items():
                page_id = variants.get(platform) or variants.get("common")
                if page_id:
                    expected[name] = page_id
            precedence_deterministic[platform] = selected == repeated
            if selected != repeated or selected != set(expected.values()):
                raise ValueError(f"platform precedence invariant failed for {platform}")
            precedence[platform] = expected

        bad_page_identity = connection.execute(
            """SELECT COUNT(*) FROM pages
               WHERE source_ref != 'tldr-pages@' || source_revision || ':' || source_path
                  OR source_revision != (SELECT value FROM artifact_metadata
                                         WHERE key = 'source_revision')"""
        ).fetchone()[0]
        orphan_lexical = connection.execute(
            """SELECT COUNT(*) FROM example_lexical AS lexical
               WHERE NOT EXISTS (
                 SELECT 1 FROM examples AS e WHERE e.example_id = lexical.example_id
               )"""
        ).fetchone()[0]
        bad_refs = connection.execute(
            """SELECT COUNT(*) FROM page_references AS r
               JOIN pages AS p ON p.page_id = r.page_id
               WHERE p.page_kind = 'operational'
                  OR NOT EXISTS (
                    SELECT 1 FROM examples AS e
                    WHERE e.page_id = r.page_id AND e.position = r.position
                  )"""
        ).fetchone()[0]
        unresolved_destinations = connection.execute(
            """SELECT COUNT(*) FROM page_references AS r
               WHERE NOT EXISTS (
                 SELECT 1 FROM pages AS destination
                 WHERE destination.page_name = r.destination_name
                   AND destination.page_kind = 'operational'
               )"""
        ).fetchone()[0]
        indexed_reference_examples = connection.execute(
            """SELECT COUNT(*) FROM example_lexical AS lexical
               JOIN examples AS example ON example.example_id = lexical.example_id
               JOIN pages AS page ON page.page_id = example.page_id
               WHERE page.page_kind != 'operational'"""
        ).fetchone()[0]
        selected_destination_errors = 0
        page_by_id = {row[0]: row for row in rows}
        for platform in sorted(evaluator.SUPPORTED_PLATFORMS):
            selected_ids = evaluator.selected_page_ids(connection, platform)
            for page_id, destination_name, _ in connection.execute(
                "SELECT page_id, destination_name, position FROM page_references"
            ):
                if page_id not in selected_ids:
                    continue
                destination_ids = [
                    candidate_id
                    for candidate_id, page in page_by_id.items()
                    if candidate_id in selected_ids
                    and page[1] == destination_name
                    and page[7] == "operational"
                ]
                if len(destination_ids) != 1:
                    selected_destination_errors += 1
        reference_counts = dict(
            connection.execute(
                "SELECT page_kind, COUNT(*) FROM pages GROUP BY page_kind"
            ).fetchall()
        )

    source_identity_passed = not any(
        (
            page_identity_errors,
            duplicate_page_ids,
            duplicate_page_source_keys,
            duplicate_page_variants,
            example_identity_errors,
            bad_page_identity,
            orphan_examples,
            orphan_lexical,
        )
    )
    reference_behavior_passed = not any(
        (
            bad_refs,
            unresolved_destinations,
            indexed_reference_examples,
            selected_destination_errors,
        )
    )
    platform_precedence_passed = all(precedence_deterministic.values()) and not (
        duplicate_page_variants
    )
    has_invariant_failure = not (
        source_identity_passed
        and reference_behavior_passed
        and platform_precedence_passed
    )
    if has_invariant_failure:
        raise ValueError("source identity or reference invariant failed")
    return {
        "platform_precedence": {
            "rule": "target platform page, then common page",
            "selected_page_ids_by_platform": precedence,
            "repeated_selection_is_identical": precedence_deterministic,
            "passed": platform_precedence_passed,
        },
        "source_identity": {
            "rule": "deterministic page/example IDs and source-backed refs validated by artifact",
            "duplicate_page_ids": duplicate_page_ids,
            "duplicate_page_source_keys": duplicate_page_source_keys,
            "duplicate_page_variants": duplicate_page_variants,
            "page_identity_errors": page_identity_errors,
            "example_identity_errors": example_identity_errors,
            "bad_page_identity_rows": bad_page_identity,
            "orphan_example_rows": orphan_examples,
            "orphan_lexical_rows": orphan_lexical,
            "identity_fields": [
                "page_id",
                "example_id",
                "source_path",
                "source_ref",
                "source_revision",
            ],
            "passed": source_identity_passed,
        },
        "reference_behavior": {
            "rule": "reference pages resolve to source-backed operational destinations; references never substitute examples",
            "page_kind_counts": reference_counts,
            "invalid_reference_rows": bad_refs,
            "unresolved_destination_rows": unresolved_destinations,
            "indexed_reference_example_count": indexed_reference_examples,
            "selected_destination_errors": selected_destination_errors,
            "passed": reference_behavior_passed,
        },
    }


def representatives(quality: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, report in quality.items():
        successes = []
        failures = []
        abstentions = []
        false_answers = []
        for task in report.get("tasks", []):
            item = {
                "task_id": task["task_id"],
                "displayed_example_ids": task["displayed_example_ids"],
                "candidate_example_ids": task["candidate_example_ids"],
            }
            if task["success_at_3"]:
                successes.append(item)
            elif task["answered"] and task["incorrect_answer"]:
                failures.append(item)
            elif task["false_answer"]:
                false_answers.append(item)
            elif not task["answered"]:
                abstentions.append(item)
        result[name] = {
            "successes": successes[:2],
            "failures": failures[:2],
            "correct_abstentions": abstentions[:2],
            "false_answers": false_answers[:2],
            "failure_observation": "No incorrect or false answers observed." if not failures and not false_answers else "Representative failures included above.",
        }
    return result


def build_provenance(args: argparse.Namespace, config: dict[str, Any], build: dict[str, Any], hybrid_config: Path) -> dict[str, Any]:
    paths = {
        "artifact": args.artifact,
        "manifest": args.manifest,
        "dataset": args.dataset,
        "hybrid_config": hybrid_config,
        "evidence_config": args.evidence_config,
    }
    digests = {name: sha256_file(path) for name, path in paths.items()}
    digests["artifact"] = sha256_file(args.artifact)
    digests["cargo_lock"] = sha256_file(ROOT / "Cargo.lock")
    network_probe = None
    if args.network_probe is not None:
        probe_text = args.network_probe.read_text(encoding="utf-8")
        if "network denied:" not in probe_text:
            raise ValueError("network probe did not record a denied socket")
        network_probe = {
            "result": "passed",
            "path": args.network_probe.name,
            "sha256": sha256_file(args.network_probe),
        }
    return {
        "input_digests_sha256": digests,
        "database": {
            "path": args.artifact.name,
            "size_bytes": args.artifact.stat().st_size,
            "sha256": digests["artifact"],
        },
        "build": build,
        "dependencies": dependency_versions(),
        "model": {
            "repository": MODEL_REPO,
            "revision": MODEL_REVISION,
            "onnxruntime_version": RUNTIME_VERSION,
            "execution_provider": config["execution_provider"],
            "file_sha256": model_digests(args.model_cache),
        },
        "code_revision": run_command(["git", "-C", str(ROOT), "rev-parse", "HEAD"]),
        "working_tree": run_command(["git", "-C", str(ROOT), "status", "--porcelain=v1"]),
        "network_probe": network_probe,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--performance-worker",
        action="store_true",
        help="run one isolated performance sample and emit JSON",
    )
    result.add_argument("--artifact", required=True, type=Path)
    result.add_argument("--manifest", required=True, type=Path)
    result.add_argument("--dataset", required=True, type=Path)
    result.add_argument("--hybrid-config", required=True, type=Path)
    result.add_argument("--evidence-config", required=True, type=Path)
    result.add_argument("--dense-helper", required=True, type=Path)
    result.add_argument("--model-cache", required=True, type=Path)
    result.add_argument("--build-metadata", required=True, type=Path)
    result.add_argument("--dense-build-metadata", required=True, type=Path)
    result.add_argument("--network-probe", required=True, type=Path)
    result.add_argument("--output", required=True, type=Path)
    return result


def load_frozen_protocol(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], Any, list[dict[str, str]], str, str]:
    config = load_evidence_config(args.evidence_config)
    evidence_config_digest = sha256_file(args.evidence_config)
    if evidence_config_digest != FROZEN_EVIDENCE_CONFIG_SHA256:
        raise ValueError("evidence config is not the committed frozen protocol")
    dataset = load_json(args.dataset)
    evaluator.validate_dataset(dataset, "holdout")
    if dataset.get("dataset_id") != config["dataset_id"]:
        raise ValueError("evidence config dataset ID does not match dataset")
    dataset_digest = sha256_file(args.dataset)
    if dataset_digest != config["dataset_sha256"]:
        raise ValueError("holdout dataset is not the committed frozen split")
    hybrid = evaluator.load_hybrid_config(args.hybrid_config)
    if hybrid.config_id != config["hybrid_config_id"]:
        raise ValueError("evidence config hybrid ID does not match hybrid config")
    uses_expected_frozen_candidate = (
        hybrid.frozen
        and hybrid.selected_candidate_id == "rrf-k60-b8-cutoff-0.50"
    )
    if not uses_expected_frozen_candidate:
        raise ValueError("evidence requires the selected frozen hybrid candidate")
    return (
        config,
        hybrid,
        query_tasks(dataset),
        evidence_config_digest,
        dataset_digest,
    )


def performance_worker(args: argparse.Namespace) -> dict[str, Any]:
    config, hybrid, tasks, _, _ = load_frozen_protocol(args)
    return run_hybrid_queries(
        args.dense_helper,
        args.artifact,
        args.model_cache,
        tasks,
        config["performance"]["warmup_queries"],
        config["performance"]["warm_queries"],
        hybrid.selected,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    config, hybrid, tasks, evidence_config_digest, dataset_digest = load_frozen_protocol(
        args
    )
    quality = {
        name: run_quality(args, name, args.hybrid_config)
        for name in config["quality"]["retrievers"]
    }
    build = {
        "lexical": require_build_metadata(args.build_metadata, "lexical"),
        "dense": require_build_metadata(args.dense_build_metadata, "dense"),
        "setup_and_download_separate": True,
        "query_network_policy": "macOS sandbox-exec deny network* (caller enforced)",
    }
    report = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": config["evidence_id"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "protocol": {
            "quality_runs_per_retriever": config["quality"]["runs_per_retriever"],
            "no_holdout_tuning_or_rerun": config["quality"]["no_holdout_tuning_or_rerun"],
            "selected_hybrid_candidate": hybrid.selected_candidate_id,
            "execution_provider": config["execution_provider"],
            "evidence_config_sha256": evidence_config_digest,
            "dataset_sha256": dataset_digest,
        },
        "quality_reports": quality,
        "deterministic_invariants": deterministic_invariants(args.artifact),
        "performance": performance_report(args, config, tasks, hybrid.selected),
        "host": host_metadata(config),
        "provenance": build_provenance(args, config, build, args.hybrid_config),
        "representative_results": representatives(quality),
        "recommendation": {
            "decision": "insufficient_evidence",
            "text": "The frozen hybrid and keyword baseline are compared on 30 small fixture tasks; this is insufficient evidence for superiority, adoption, or a product asset change.",
        },
        "limitations": [
            "The holdout has 10 answerable and 20 unanswerable tasks; rates are reported with counts and denominators and are unstable at this size.",
            "Fresh-process p95 uses five runs and warm p95 uses one process workload; these are engineering measurements, not capacity guarantees.",
            "No holdout tuning or rerun was performed after observing results.",
            "Offline query networking is enforced by the caller's sandbox; setup/download is a separate networked step.",
        ],
        "milestone_2_remaining_work": [
            "CLI integration",
            "automatic matching-asset setup",
            "explicit updates",
            "packaging investigation",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.performance_worker:
            print(json.dumps(performance_worker(args), sort_keys=True))
            return 0
        report = run(args)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as error:
        print(f"heldout evidence failed: {error}", file=sys.stderr)
        return 2
    print(f"wrote {args.output} ({len(report['quality_reports'])} quality reports)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
