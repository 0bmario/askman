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
from pathlib import Path, PurePosixPath
from textwrap import dedent
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 33_031
MIN_SUCCESS_AT_1_GAIN = 0.05
MAX_REGRESSION = 0.20
DEFAULT_RETRIEVAL_CONFIGURATION = {
    "configuration_id": "focused-v1",
    "dense_recipe": "main-compatible",
    "query_mode": "focused-v1",
    "candidate_budget": 8,
    "ranking": "raw cosine distance, ascending",
    "distance_cutoff": 0.55,
    "example_selection": "one example per page before display",
    "display_limit": 3,
    "fusion": "none",
    "abstention": "distance cutoff and scoped negation guards",
}
FROZEN_MANIFEST_SHA256 = (
    "4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc"
)
FROZEN_DEV_DATASET_SHA256 = (
    "216c0e26f24fda7df197011be4f8add33b6852b7907b32966b0c77e0a26c947d"
)
FROZEN_HOLDOUT_DATASET_SHA256 = (
    "1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418"
)
FRESH_HOLDOUT_FREEZE_ID = "fresh-holdout-v1-freeze-2026-09-26"
FRESH_HOLDOUT_MANIFEST_SHA256 = (
    "7463ccb782cf971b4893f369c899f408212306020c68e471b72c146b2da68f1a"
)
FRESH_HOLDOUT_DATASET_SHA256 = (
    "7fe11e153b64941c91233b756543487ebdd34e17bcca7b935a55f8f16a6fb2a0"
)
DEV_EXTENSION_FREEZE_ID = "askman-dev-extension-v1-freeze-2026-09-26"
DEV_EXTENSION_MANIFEST_SHA256 = (
    "9dcf13de29e6b0969344e6b2c64b298f9550ac320dad67dfca4a8a9ad9a096d5"
)
DEV_EXTENSION_DATASET_SHA256 = (
    "6c113bed013be3f532a8287c58a4f257347585c2be963d6c3b475d41ecc49905"
)
# Deterministic evaluation-corpus DB rebuilt by the main importer at
# 8bd9fa296ea7e2f461202091f2ade47221bc8a0e from the frozen e1cb... snapshot.
# This pins the main retrieval vectors for the 142-example evaluation corpus.
PINNED_MAIN_DATABASE_SHA256 = (
    "ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db"
)
# Last committed parser-v3 build used by the frozen evaluation-v2 labels.
FROZEN_CORPUS_REFERENCE_REF = "f61e3afa83e2bb6171c702f2bf8107ad40e6c267"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Older macOS /usr/bin/time reports "maximum resident set size: <bytes>";
# current macOS reports "<bytes> peak memory footprint". Both are bytes.
PEAK_MEMORY_MAC = re.compile(r"maximum resident set size:\s*(\d+)")
PEAK_MEMORY_MAC_FOOTPRINT = re.compile(
    r"^\s*(\d+)\s+peak memory footprint\s*$", re.MULTILINE
)
PEAK_MEMORY_LINUX = re.compile(
    r"Maximum resident set size \(kbytes\):\s*(\d+)", re.IGNORECASE
)
DisplayIdentity = tuple[str, ...] | None
VisibleResultKey = tuple[str, str, str, str]
ExampleIndex = dict[VisibleResultKey, dict[str, tuple[str, ...]]]


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
    displayed_example_id_candidates: tuple[DisplayIdentity, ...]
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
    manifest: Path,
    dev_dataset: Path,
    holdout_dataset: Path | None = None,
    *,
    allow_custom_dev_dataset: bool = False,
) -> None:
    expected = {
        manifest: FROZEN_MANIFEST_SHA256,
    }
    if not allow_custom_dev_dataset:
        expected[dev_dataset] = FROZEN_DEV_DATASET_SHA256
    if holdout_dataset is not None:
        expected[holdout_dataset] = FROZEN_HOLDOUT_DATASET_SHA256
    for path, expected_digest in expected.items():
        if not path.is_file():
            raise ValueError(f"frozen evaluation input is missing: {path}")
        actual_digest = sha256_file(path)
        if actual_digest != expected_digest:
            raise ValueError(
                f"frozen evaluation input digest mismatch for {path}: "
                f"expected {expected_digest}, got {actual_digest}"
            )


def validate_custom_dev_freeze(
    manifest_path: Path,
    dataset_override: Path | None,
    repo: Path,
) -> tuple[dict[str, Any], Path]:
    if sha256_file(manifest_path) != DEV_EXTENSION_MANIFEST_SHA256:
        raise ValueError("custom development freeze manifest digest is not pinned")
    manifest = load_json(manifest_path)
    if manifest.get("freeze_id") != DEV_EXTENSION_FREEZE_ID:
        raise ValueError("custom development freeze ID is not pinned")
    if manifest.get("status") != "frozen_dev_only" or manifest.get("split") != "dev":
        raise ValueError("custom development manifest must describe a frozen dev-only split")
    if manifest.get("authorization_required_before_holdout_scoring") is not True:
        raise ValueError("custom development manifest must preserve the holdout authorization rule")
    if manifest.get("holdout_accessed") is not False:
        raise ValueError("custom development manifest records holdout access")
    if manifest.get("development_gate_runs_at_freeze") != 0:
        raise ValueError("custom development manifest was not frozen before CLI evaluation")
    if manifest.get("release_gate_runs_at_freeze") != 0:
        raise ValueError("custom development manifest records a release-gate run")

    relative_path = manifest.get("dataset_path")
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("custom development manifest has an invalid dataset path")
    dataset_path = (repo / relative_path).resolve()
    if dataset_override is not None and dataset_override.resolve() != dataset_path:
        raise ValueError("custom development dataset path differs from its freeze manifest")
    if not dataset_path.is_file():
        raise ValueError(f"custom development dataset is missing: {dataset_path}")
    if manifest.get("dataset_sha256") != DEV_EXTENSION_DATASET_SHA256:
        raise ValueError("custom development dataset digest is not pinned by its manifest")
    if sha256_file(dataset_path) != DEV_EXTENSION_DATASET_SHA256:
        raise ValueError("custom development dataset digest differs from its freeze")

    corpus = manifest.get("corpus")
    if not isinstance(corpus, dict):
        raise ValueError("custom development manifest is missing its corpus identity")
    corpus_manifest_path = corpus.get("manifest_path")
    corpus_manifest_digest = corpus.get("manifest_sha256")
    if not isinstance(corpus_manifest_path, str) or not isinstance(
        corpus_manifest_digest, str
    ):
        raise ValueError("custom development corpus manifest identity is invalid")
    pinned_corpus_manifest = (repo / corpus_manifest_path).resolve()
    if (
        not pinned_corpus_manifest.is_file()
        or sha256_file(pinned_corpus_manifest) != corpus_manifest_digest
    ):
        raise ValueError("custom development corpus manifest is missing or changed")
    return manifest, dataset_path


def validate_fresh_holdout_freeze(
    manifest_path: Path,
    dataset_override: Path | None,
    repo: Path,
) -> tuple[dict[str, Any], Path]:
    if sha256_file(manifest_path) != FRESH_HOLDOUT_MANIFEST_SHA256:
        raise ValueError("fresh holdout freeze manifest digest is not the pinned value")
    manifest = load_json(manifest_path)
    if manifest.get("freeze_id") != FRESH_HOLDOUT_FREEZE_ID:
        raise ValueError("fresh holdout freeze ID is not the pinned value")
    if manifest.get("status") != "frozen_unscored":
        raise ValueError("fresh holdout must be frozen and unscored before evaluation")
    if manifest.get("authorization_required_before_candidate_scoring") is not True:
        raise ValueError("fresh holdout manifest does not require scoring authorization")
    if manifest.get("candidate_runs_on_this_split") != 0:
        raise ValueError("fresh holdout already records candidate access")
    if manifest.get("release_gate_runs_on_this_split") != 0:
        raise ValueError("fresh holdout already records a release-gate run")

    dataset_record = manifest.get("artifacts", {}).get("dataset")
    if not isinstance(dataset_record, dict):
        raise ValueError("fresh holdout manifest is missing its dataset record")
    if dataset_record.get("sha256") != FRESH_HOLDOUT_DATASET_SHA256:
        raise ValueError("fresh holdout dataset digest is not the pinned value")
    relative_path = dataset_record.get("path")
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("fresh holdout manifest has an invalid dataset path")
    dataset_path = (repo / relative_path).resolve()
    if dataset_override is not None and dataset_override.resolve() != dataset_path:
        raise ValueError("holdout dataset path differs from its frozen manifest")
    if not dataset_path.is_file():
        raise ValueError(f"fresh holdout dataset is missing: {dataset_path}")
    if sha256_file(dataset_path) != FRESH_HOLDOUT_DATASET_SHA256:
        raise ValueError("fresh holdout dataset digest is not the pinned value")
    corpus_record = manifest.get("corpus")
    if not isinstance(corpus_record, dict):
        raise ValueError("fresh holdout manifest is missing its corpus record")
    corpus_manifest_relative_path = corpus_record.get("manifest_path")
    corpus_manifest_digest = corpus_record.get("manifest_sha256")
    if not isinstance(corpus_manifest_relative_path, str) or not isinstance(
        corpus_manifest_digest, str
    ):
        raise ValueError("fresh holdout corpus manifest identity is invalid")
    corpus_manifest_path = (repo / corpus_manifest_relative_path).resolve()
    has_corpus_manifest = (
        corpus_manifest_path.is_file()
        and sha256_file(corpus_manifest_path) == corpus_manifest_digest
    )
    if not has_corpus_manifest:
        raise ValueError("fresh holdout corpus manifest is missing or has changed")
    return manifest, dataset_path


def validate_fresh_holdout_dataset(
    dataset: dict[str, Any], freeze: dict[str, Any]
) -> None:
    """Validate the independent one-intent-per-family holdout freeze."""
    if dataset.get("split") != "holdout":
        raise ValueError("fresh independent dataset split must be holdout")
    if dataset.get("scorer_version") != evaluator.SCORER_VERSION:
        raise ValueError("fresh independent dataset uses an unsupported scorer")
    tasks = dataset.get("tasks")
    declared_task_count = freeze.get("intents", {}).get("task_count")
    if not isinstance(tasks, list) or len(tasks) != declared_task_count:
        raise ValueError("fresh holdout task count differs from its freeze manifest")
    if dataset.get("task_count") != declared_task_count:
        raise ValueError("fresh holdout declared task count is inconsistent")

    frozen_corpus = freeze.get("corpus")
    corpus = dataset.get("corpus")
    if not isinstance(frozen_corpus, dict) or not isinstance(corpus, dict):
        raise ValueError("fresh holdout corpus identity is missing")
    for field in ("source_revision", "source_digest", "parser_version"):
        if corpus.get(field) != frozen_corpus.get(field):
            raise ValueError(f"fresh holdout corpus differs from its freeze manifest: {field}")
    source_revision = frozen_corpus.get("source_revision")
    expected_corpus_ids = {
        f"{source_revision}:{frozen_corpus.get('source_digest')}",
        # The frozen fresh-holdout dataset predates digest-based corpus IDs.
        f"tldr-pages@{source_revision}",
    }
    if corpus.get("corpus_id") not in expected_corpus_ids:
        raise ValueError("fresh holdout corpus ID is inconsistent")
    if corpus.get("manifest_sha256") not in (None, frozen_corpus.get("manifest_sha256")):
        raise ValueError("fresh holdout corpus manifest digest is inconsistent")

    expected_distribution = freeze.get("distribution")
    expected_labels = freeze.get("labels")
    if not isinstance(expected_distribution, dict) or not isinstance(expected_labels, dict):
        raise ValueError("fresh holdout label distribution is missing from its freeze")
    expected_task_count = expected_labels.get("answerable", 0) + expected_labels.get(
        "abstain", 0
    )
    if expected_task_count != declared_task_count:
        raise ValueError("fresh holdout label counts do not match its task count")

    task_ids: set[str] = set()
    families: set[str] = set()
    by_platform: dict[str, dict[str, int]] = {}
    answerable_count = 0
    for task in tasks:
        required = {
            "id",
            "split",
            "family",
            "question",
            "platform",
            "answerable",
            "acceptable_example_ids",
            "rationale",
        }
        if not isinstance(task, dict) or not required <= task.keys():
            raise ValueError("fresh holdout task is missing required fields")
        task_id = task["id"]
        family = task["family"]
        platform_name = task["platform"]
        if not isinstance(task_id, str) or not task_id or task_id in task_ids:
            raise ValueError("fresh holdout task IDs must be unique and non-empty")
        if not isinstance(family, str) or not family or family in families:
            raise ValueError("fresh holdout scenario families must be unique and non-empty")
        if task["split"] != "holdout":
            raise ValueError("fresh holdout task has the wrong split")
        if not isinstance(task["question"], str) or not task["question"].strip():
            raise ValueError(f"fresh holdout task {task_id} has an empty question")
        if not isinstance(task["rationale"], str) or not task["rationale"].strip():
            raise ValueError(f"fresh holdout task {task_id} has an empty rationale")
        if platform_name not in evaluator.SUPPORTED_PLATFORMS:
            raise ValueError(f"fresh holdout task {task_id} has an unsupported platform")
        if not isinstance(task["answerable"], bool):
            raise ValueError(f"fresh holdout task {task_id} has an invalid answerability label")
        acceptable_ids = task["acceptable_example_ids"]
        if not isinstance(acceptable_ids, list) or any(
            not isinstance(example_id, str) or not example_id
            for example_id in acceptable_ids
        ):
            raise ValueError(f"fresh holdout task {task_id} has invalid acceptable IDs")
        if len(acceptable_ids) != len(set(acceptable_ids)):
            raise ValueError(f"fresh holdout task {task_id} repeats an acceptable ID")
        if task["answerable"] and not acceptable_ids:
            raise ValueError(f"fresh holdout task {task_id} has no acceptable example ID")
        if not task["answerable"] and acceptable_ids:
            raise ValueError(f"unanswerable fresh holdout task {task_id} has acceptable IDs")

        task_ids.add(task_id)
        families.add(family)
        counts = by_platform.setdefault(
            platform_name, {"tasks": 0, "answerable": 0, "abstain": 0}
        )
        counts["tasks"] += 1
        label_name = "answerable" if task["answerable"] else "abstain"
        counts[label_name] += 1
        answerable_count += task["answerable"]

    if answerable_count != expected_labels.get("answerable"):
        raise ValueError("fresh holdout answerable count differs from its freeze manifest")
    if declared_task_count - answerable_count != expected_labels.get("abstain"):
        raise ValueError("fresh holdout abstention count differs from its freeze manifest")
    if by_platform != expected_distribution:
        raise ValueError("fresh holdout platform distribution differs from its freeze manifest")


def validate_independent_dataset_pair(
    development: dict[str, Any], holdout: dict[str, Any]
) -> None:
    evaluator.validate_dataset(development, "dev")
    development_ids = {task["id"] for task in development["tasks"]}
    holdout_ids = {task["id"] for task in holdout["tasks"]}
    if development_ids & holdout_ids:
        raise ValueError("development and independent holdout task IDs must be disjoint")
    development_families = {task["family"] for task in development["tasks"]}
    holdout_families = {task["family"] for task in holdout["tasks"]}
    if development_families & holdout_families:
        raise ValueError("development and independent holdout families must be disjoint")
    for field in ("source_revision", "source_digest"):
        if development.get("corpus", {}).get(field) != holdout.get("corpus", {}).get(
            field
        ):
            raise ValueError(f"development and independent holdout {field} must match")


def validate_custom_dev_dataset(
    dataset: dict[str, Any], freeze: dict[str, Any]
) -> None:
    if dataset.get("schema_version") != evaluator.DEV_EXTENSION_SCHEMA_VERSION:
        raise ValueError("custom development data must use schema 3")
    evaluator.validate_dataset(dataset, "dev")
    if dataset.get("freeze_id") != freeze.get("freeze_id"):
        raise ValueError("custom development dataset freeze ID differs from its manifest")
    for dataset_field, manifest_field in (
        ("cohort_id", "cohort_id"),
        ("dataset_id", "dataset_id"),
        ("schema_version", "dataset_schema_version"),
        ("task_count", "task_count"),
        ("answerable_task_count", "answerable_task_count"),
        ("unanswerable_task_count", "unanswerable_task_count"),
        ("corpus", "corpus"),
    ):
        if dataset.get(dataset_field) != freeze.get(manifest_field):
            raise ValueError(
                f"custom development dataset differs from its manifest: {dataset_field}"
            )
    if len({task["family"] for task in dataset["tasks"]}) != freeze.get(
        "family_count"
    ):
        raise ValueError("custom development family count differs from its manifest")
    platform_distribution: dict[str, dict[str, int]] = {}
    for platform_name in evaluator.SUPPORTED_PLATFORMS:
        platform_tasks = [
            task for task in dataset["tasks"] if task["platform"] == platform_name
        ]
        platform_distribution[platform_name] = {
            "tasks": len(platform_tasks),
            "answerable": sum(task["answerable"] for task in platform_tasks),
            "unanswerable": sum(not task["answerable"] for task in platform_tasks),
        }
    if platform_distribution != freeze.get("platform_distribution"):
        raise ValueError("custom development platform distribution differs from its manifest")


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


def bake_ort_rpath(binary: Path) -> str | None:
    """Embed the pinned ONNX Runtime directory for a dynamic macOS binary.

    Static release binaries have no ONNX Runtime load command and need no
    rpath. For dynamic binaries, sandbox-exec strips DYLD_* from the child
    environment, so the runtime directory must be embedded in the binary.
    """
    if platform.system() != "Darwin":
        return None
    listed = subprocess.run(
        ["otool", "-L", str(binary)], check=False, capture_output=True, text=True
    )
    if listed.returncode != 0:
        raise RuntimeError(f"could not inspect linked libraries for {binary}:\n{listed.stderr}")
    load_commands = listed.stdout.splitlines()[1:]
    if not any("onnxruntime" in line.lower() for line in load_commands):
        return None

    ort_lib_location = os.environ.get("ORT_LIB_LOCATION")
    if not ort_lib_location:
        raise RuntimeError(
            "dynamic macOS query binaries need ORT_LIB_LOCATION so the gate can "
            "bake their ONNX Runtime rpath"
        )
    rpath = str(Path(ort_lib_location) / "lib")
    load_commands = subprocess.run(
        ["otool", "-l", str(binary)], check=False, capture_output=True, text=True
    )
    if load_commands.returncode != 0:
        raise RuntimeError(f"could not inspect rpaths for {binary}:\n{load_commands.stderr}")
    for line in load_commands.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "path" and parts[1] == rpath:
            return rpath
    install = subprocess.run(
        ["install_name_tool", "-add_rpath", rpath, str(binary)],
        check=False,
        capture_output=True,
        text=True,
    )
    if install.returncode != 0:
        raise RuntimeError(f"could not bake rpath into {binary}:\n{install.stderr}")
    return rpath


def working_tree_source_sha256(repo: Path) -> str:
    paths = [repo / "Cargo.toml", repo / "Cargo.lock", repo / "build.rs"]
    cargo_config = repo / ".cargo"
    if cargo_config.is_dir():
        paths.extend(path for path in cargo_config.rglob("*") if path.is_file())
    source_dir = repo / "src"
    if source_dir.is_dir():
        paths.extend(path for path in source_dir.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        relative = path.relative_to(repo).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def build_binary(
    repo: Path,
    ref: str,
    label: str,
    root: Path,
    *,
    working_tree: bool = False,
) -> dict[str, Any]:
    """Build a ref or the current checkout in an isolated Cargo target."""
    worktree = root / f"{label}-source"
    target = root / f"{label}-target"
    binary = target / "release" / ("askman.exe" if os.name == "nt" else "askman")
    started = time.perf_counter()
    if working_tree:
        worktree = repo
    else:
        run_command(["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree), ref])
    try:
        environment = os.environ.copy()
        environment["CARGO_TARGET_DIR"] = str(target)
        # Match the shipped Cargo configuration and release artifacts: link
        # the pinned ONNX Runtime statically instead of selecting a host copy.
        environment["ORT_PREFER_DYNAMIC_LINK"] = "0"
        environment["LIBONNXRUNTIME_NO_PKG_CONFIG"] = "1"
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
        rpath = bake_ort_rpath(binary)
        report = {
            "ref": "working-tree" if working_tree else ref,
            "commit": git_revision(worktree, "HEAD"),
            "cargo_lock_sha256": sha256_file(worktree / "Cargo.lock"),
            "binary_sha256": sha256_file(binary),
            "binary_bytes": binary.stat().st_size,
            "binary": str(binary),
            "ort_rpath": rpath,
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
        if working_tree:
            status = subprocess.run(
                ["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=all"],
                check=True,
                capture_output=True,
                text=True,
            )
            report["working_tree_source_sha256"] = working_tree_source_sha256(repo)
            report["working_tree_status"] = status.stdout.splitlines()
        return report
    finally:
        if not working_tree:
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
    footprint = PEAK_MEMORY_MAC_FOOTPRINT.search(stderr)
    if footprint:
        return int(footprint.group(1))
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


def normalize_command_text(value: str) -> str:
    # Both CLI generations render example commands with tldr `{{placeholder}}`
    # braces stripped; compare commands in that normalized space.
    return value.replace("{{", "").replace("}}", "").strip()


def normalize_page_command_text(value: str, platform_name: str) -> str:
    command = normalize_command_text(value)
    if platform_name == "windows":
        # The legacy importer lowercases Windows page commands; PowerShell
        # command names are case-insensitive, while the bundle preserves source casing.
        return command.lower()
    return command


def normalize_description_text(value: str) -> str:
    return " ".join(visible_description_text(value).split())


def visible_description_text(value: str) -> str:
    index = value.find("More information:")
    cleaned = value[:index] if index != -1 else value
    return cleaned.strip()


def parse_displayed_results(stdout: str) -> list[dict[str, str]]:
    """Extract each example together with its user-visible page identity."""
    lines = dedent(clean_output(stdout)).splitlines()
    results: list[dict[str, str]] = []
    cursor = 0
    while cursor < len(lines):
        line = lines[cursor]
        if not line.strip() or line.strip() == "No good matches found.":
            cursor += 1
            continue
        if line.strip() == "Examples:":
            block_results, cursor = parse_example_block(lines, cursor, "", "")
            results.extend(block_results)
            continue
        if line.startswith(("  ", "\t")):
            cursor += 1
            continue

        page_command = line.strip()
        cursor += 1
        page_description_lines: list[str] = []
        while cursor < len(lines) and lines[cursor].strip() != "Examples:":
            description_line = lines[cursor]
            if not description_line.strip():
                break
            if description_line.startswith(("  ", "\t")):
                break
            if not description_line.strip().startswith(("(Ranking score:", "(Distance:")):
                page_description_lines.append(description_line.strip())
            cursor += 1
        page_description = visible_description_text("\n".join(page_description_lines))
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor < len(lines) and lines[cursor].strip() == "Examples:":
            block_results, cursor = parse_example_block(
                lines, cursor, page_command, page_description
            )
            results.extend(block_results)
    return results


def parse_example_block(
    lines: Sequence[str],
    examples_index: int,
    page_command: str,
    page_description: str,
) -> tuple[list[dict[str, str]], int]:
    results: list[dict[str, str]] = []
    cursor = examples_index + 1
    while cursor < len(lines):
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor >= len(lines):
            break
        description_line = lines[cursor]
        if not description_line.startswith("  ") or description_line.startswith("   "):
            break
        command_index = cursor + 1
        if command_index >= len(lines) or not lines[command_index].startswith("   "):
            break
        description = description_line.strip()
        command = lines[command_index].strip()
        if description and command:
            results.append(
                {
                    "page_command": page_command,
                    "page_description": page_description,
                    "description": description,
                    "command": command,
                }
            )
        cursor = command_index + 1
    return results, cursor


def example_index(bundle: Path) -> ExampleIndex:
    database = bundle / "matching.db"
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """SELECT p.platform, p.command, p.description,
                      e.example_id, e.description, e.command
               FROM examples AS e
               JOIN pages AS p ON p.page_id = e.page_id
               ORDER BY p.platform, e.example_id"""
        ).fetchall()
    index: dict[VisibleResultKey, dict[str, list[str]]] = {}
    for platform_name, page_command, page_description, example_id, description, command in rows:
        key = (
            normalize_page_command_text(page_command, platform_name),
            normalize_description_text(page_description),
            normalize_description_text(description),
            normalize_command_text(command),
        )
        index.setdefault(key, {}).setdefault(platform_name, []).append(example_id)
    return {
        key: {
            platform_name: tuple(sorted(set(example_ids)))
            for platform_name, example_ids in platform_examples.items()
        }
        for key, platform_examples in index.items()
    }


def eligible_result_platforms(task_platform: str) -> set[str]:
    if task_platform not in {"common", "linux", "osx", "windows"}:
        raise ValueError(f"unsupported task platform: {task_platform}")
    if task_platform == "common":
        host_platform = {
            "Darwin": "osx",
            "Linux": "linux",
            "Windows": "windows",
        }.get(platform.system())
        if host_platform is None:
            raise RuntimeError(
                f"unsupported host platform for common-query mapping: {platform.system()}"
            )
        task_platform = host_platform
    return {"common", task_platform}


def validate_main_data_compatibility(
    main_data_dir: Path,
    bundle: Path,
    *,
    allow_unpinned_main_database: bool = False,
) -> dict[str, Any]:
    main_database_sha256 = sha256_file(main_data_dir / "commands.db")
    main_database_matches_pinned_baseline = (
        main_database_sha256 == PINNED_MAIN_DATABASE_SHA256
    )
    if not main_database_matches_pinned_baseline and not allow_unpinned_main_database:
        raise ValueError(
            "main commands.db does not match the pinned evaluation baseline digest; "
            "only --dev-only may use an unpinned scratch database"
        )

    manifest = load_json(bundle / "manifest.json")
    source = manifest.get("source")
    source_digest = source.get("digest") if isinstance(source, dict) else None
    if not isinstance(source_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise ValueError("candidate bundle source digest is invalid")
    source_revision = source.get("revision") if isinstance(source, dict) else None
    parser_version = manifest.get("parser_version")
    if not isinstance(source_revision, str) or not source_revision.strip():
        raise ValueError("candidate bundle source revision is invalid")
    if not isinstance(parser_version, str) or not parser_version.strip():
        raise ValueError("candidate bundle parser version is invalid")

    model = manifest.get("embedding_model")
    assets = model.get("assets") if isinstance(model, dict) else None
    if not isinstance(assets, list) or not assets:
        raise ValueError("candidate bundle model asset inventory is missing")
    bundle_model_root = (bundle / "model-cache").resolve()
    main_model_root = (main_data_dir / "models").resolve()
    model_asset_digests: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("candidate bundle model asset entry is invalid")
        asset_path = asset.get("path")
        size_bytes = asset.get("size_bytes")
        expected_digest = asset.get("sha256")
        if (
            not isinstance(asset_path, str)
            or "\\" in asset_path
            or not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes <= 0
            or not isinstance(expected_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
        ):
            raise ValueError("candidate bundle model asset entry is invalid")
        relative_parts = PurePosixPath(asset_path).parts
        if (
            len(relative_parts) < 2
            or relative_parts[0] != "model-cache"
            or any(part in {".", ".."} for part in relative_parts)
        ):
            raise ValueError("candidate bundle model asset path is invalid")
        relative_path = Path(*relative_parts[1:])
        relative_asset_path = relative_path.as_posix()
        if relative_asset_path in model_asset_digests:
            raise ValueError("candidate bundle model asset inventory has duplicate paths")
        bundle_asset = bundle / Path(*relative_parts)
        main_asset = main_model_root / relative_path
        try:
            bundle_asset.resolve().relative_to(bundle_model_root)
            main_asset.resolve().relative_to(main_model_root)
        except ValueError as error:
            raise ValueError("model asset path escapes its model cache") from error
        if not bundle_asset.is_file() or bundle_asset.stat().st_size != size_bytes:
            raise ValueError("candidate bundle model asset does not match its manifest")
        if sha256_file(bundle_asset) != expected_digest:
            raise ValueError("candidate bundle model asset does not match its manifest")
        if (
            not main_asset.is_file()
            or main_asset.stat().st_size != size_bytes
            or sha256_file(main_asset) != expected_digest
        ):
            raise ValueError(f"main model asset mismatch: {relative_path.as_posix()}")
        model_asset_digests[relative_asset_path] = expected_digest

    comparison_output = run_command(
        [
            "cargo",
            "run",
            "--quiet",
            "--locked",
            "--offline",
            "--features",
            "dev",
            "--bin",
            "tldr_subset",
            "--",
            "compare-visible-corpus",
            "--main-database",
            str(main_data_dir / "commands.db"),
            "--candidate-database",
            str(bundle / "matching.db"),
        ],
        cwd=ROOT,
    )
    try:
        comparison = json.loads(comparison_output)
    except json.JSONDecodeError as error:
        raise ValueError("visible corpus comparison returned invalid JSON") from error
    if not isinstance(comparison, dict):
        raise ValueError("visible corpus comparison returned invalid evidence")
    example_count = comparison.get("visible_corpus_example_count")
    inventory_digest = comparison.get("visible_corpus_examples_sha256")
    if (
        isinstance(example_count, bool)
        or not isinstance(example_count, int)
        or example_count <= 0
        or not isinstance(inventory_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", inventory_digest)
    ):
        raise ValueError("visible corpus comparison returned invalid evidence")
    return {
        "candidate_parser_version": parser_version,
        "candidate_source_revision": source_revision,
        "candidate_source_digest": source_digest,
        "main_database_sha256": main_database_sha256,
        "main_database_matches_pinned_baseline": main_database_matches_pinned_baseline,
        "visible_corpus_example_count": example_count,
        "visible_corpus_examples_sha256": inventory_digest,
        "model_asset_count": len(assets),
        "model_asset_digests": dict(sorted(model_asset_digests.items())),
        "model_assets_match": True,
    }


def validate_benchmark_corpus_compatibility(
    dataset: dict[str, Any],
    candidate_corpus: dict[str, str],
    split_name: str,
    record_equivalence: dict[str, Any] | None = None,
    allow_legacy_tldr_corpus_id: bool = False,
) -> dict[str, Any]:
    corpus = dataset.get("corpus")
    if not isinstance(corpus, dict):
        raise ValueError(f"{split_name} benchmark corpus identity is missing")

    identity: dict[str, str] = {}
    for field in ("parser_version", "source_revision", "source_digest"):
        value = corpus.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{split_name} benchmark corpus identity is invalid: {field}")
        identity[field] = value

    expected_corpus_id = f"{identity['source_revision']}:{identity['source_digest']}"
    is_frozen_legacy_tldr_id = (
        allow_legacy_tldr_corpus_id
        and corpus.get("corpus_id") == f"tldr-pages@{identity['source_revision']}"
    )
    if (
        corpus.get("corpus_id") != expected_corpus_id
        and not is_frozen_legacy_tldr_id
    ):
        raise ValueError(f"{split_name} benchmark corpus ID is inconsistent")

    for field in ("source_revision", "source_digest"):
        expected = identity[field]
        if candidate_corpus.get(field) != expected:
            raise ValueError(
                f"{split_name} benchmark corpus mismatch for {field}: "
                f"frozen labels declare {expected}, candidate bundle has "
                f"{candidate_corpus.get(field)}; labels are invalid for this bundle"
            )

    if candidate_corpus.get("parser_version") != identity["parser_version"]:
        if (
            record_equivalence is None
            or not record_equivalence.get("records_identical")
            or record_equivalence.get("reference_parser_version")
            != identity["parser_version"]
            or record_equivalence.get("candidate_parser_version")
            != candidate_corpus.get("parser_version")
        ):
            raise ValueError(
                f"{split_name} benchmark parser mismatch requires exact record-equivalence evidence"
            )
        return {
            **identity,
            "candidate_parser_version": candidate_corpus["parser_version"],
            "matches_candidate_bundle": True,
            "parser_compatibility": "exact-record-equivalence",
            "record_equivalence": record_equivalence,
        }

    return {**identity, "matches_candidate_bundle": True, "parser_compatibility": "exact"}


def corpus_record_inventory(database: Path) -> list[tuple[Any, ...]]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """SELECT e.example_id, e.page_id, p.platform, p.command,
                      p.description, e.description, e.command
               FROM examples AS e
               JOIN pages AS p ON p.page_id = e.page_id
               ORDER BY e.example_id"""
        ).fetchall()
    return rows


def build_corpus_reference(
    repo: Path,
    ref: str,
    manifest: Path,
    snapshot: Path,
    root: Path,
) -> tuple[Path, dict[str, Any]]:
    worktree = root / "corpus-reference-source"
    target = root / "corpus-reference-target"
    artifact = root / "corpus-reference.db"
    run_command(["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree), ref])
    try:
        environment = os.environ.copy()
        environment["CARGO_TARGET_DIR"] = str(target)
        environment["ORT_PREFER_DYNAMIC_LINK"] = "0"
        environment["LIBONNXRUNTIME_NO_PKG_CONFIG"] = "1"
        build = subprocess.run(
            [
                "cargo",
                "build",
                "--locked",
                "--offline",
                "--features",
                "dev",
                "--bin",
                "tldr_subset",
            ],
            cwd=worktree,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if build.returncode != 0:
            raise RuntimeError(
                "corpus reference build failed:\n"
                f"{build.stdout}\n{build.stderr}"
            )
        binary = target / "debug" / ("tldr_subset.exe" if os.name == "nt" else "tldr_subset")
        command = [
            str(binary),
            "build",
            "--manifest",
            str(manifest),
            "--snapshot",
            str(snapshot),
            "--output",
            str(artifact),
        ]
        completed = subprocess.run(
            command,
            cwd=worktree,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "corpus reference artifact build failed:\n"
                f"{completed.stdout}\n{completed.stderr}"
            )
        return artifact, {
            "ref": ref,
            "commit": git_revision(worktree, "HEAD"),
            "manifest_sha256": sha256_file(manifest),
            "binary_sha256": sha256_file(binary),
            "artifact_sha256": sha256_file(artifact),
            "command": command,
        }
    finally:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
            check=False,
            capture_output=True,
            text=True,
        )


def verify_corpus_record_equivalence(
    repo: Path,
    dataset: dict[str, Any],
    candidate_corpus: dict[str, str],
    bundle: Path,
    manifest: Path,
    snapshot: Path,
    reference_ref: str,
    scratch: Path,
) -> dict[str, Any]:
    frozen_corpus = dataset["corpus"]
    if sha256_file(manifest) != frozen_corpus.get("manifest_sha256"):
        raise ValueError("corpus reference manifest does not match frozen label provenance")
    reference_database, reference_build = build_corpus_reference(
        repo, reference_ref, manifest, snapshot, scratch
    )
    reference_records = corpus_record_inventory(reference_database)
    candidate_records = corpus_record_inventory(bundle / "matching.db")
    reference_digest = hashlib.sha256(
        json.dumps(reference_records, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    candidate_digest = hashlib.sha256(
        json.dumps(candidate_records, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    with sqlite3.connect(reference_database) as reference_connection:
        reference_metadata = dict(
            reference_connection.execute("SELECT key, value FROM artifact_metadata")
        )
    if reference_metadata.get("parser_version") != frozen_corpus.get("parser_version"):
        raise ValueError("corpus reference ref does not build the frozen parser version")
    if reference_metadata.get("source_revision") != frozen_corpus.get("source_revision"):
        raise ValueError("corpus reference source revision differs from frozen labels")
    if reference_metadata.get("source_digest") != frozen_corpus.get("source_digest"):
        raise ValueError("corpus reference source digest differs from frozen labels")
    records_identical = reference_records == candidate_records
    if not records_identical:
        raise ValueError(
            "candidate corpus records differ from the parser version used for frozen labels"
        )
    return {
        "records_identical": True,
        "reference_parser_version": reference_metadata["parser_version"],
        "candidate_parser_version": candidate_corpus["parser_version"],
        "source_revision": reference_metadata["source_revision"],
        "source_digest": reference_metadata["source_digest"],
        "reference_example_count": len(reference_records),
        "candidate_example_count": len(candidate_records),
        "reference_inventory_sha256": reference_digest,
        "candidate_inventory_sha256": candidate_digest,
        "reference_build": reference_build,
    }


def score_ids(
    task: dict[str, Any],
    displayed_id_candidates: Sequence[DisplayIdentity],
    *,
    displayed_result_count: int | None = None,
) -> dict[str, Any]:
    acceptable = set(task["acceptable_example_ids"])
    answerable = bool(task["answerable"])
    displayed = list(displayed_id_candidates)
    unique_displayed_ids = [
        identity[0] if identity is not None and len(identity) == 1 else None
        for identity in displayed
    ]
    displayed_id_candidate_lists = [
        list(identity) if identity is not None else None for identity in displayed
    ]
    result_count = len(displayed) if displayed_result_count is None else displayed_result_count
    answered = result_count > 0
    # The CLI omits source identity, so identical visible results stay a set.
    success_at_1 = (
        answerable
        and bool(displayed)
        and displayed[0] is not None
        and bool(acceptable.intersection(displayed[0]))
    )
    success_at_3 = answerable and bool(
        acceptable.intersection(
            example_id
            for identity in displayed[:3]
            if identity is not None
            for example_id in identity
        )
    )
    return {
        "task_id": task["id"],
        "displayed_example_ids": unique_displayed_ids,
        "displayed_example_id_candidates": displayed_id_candidate_lists,
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
                    "displayed_example_id_candidates": outcome[
                        "displayed_example_id_candidates"
                    ],
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
        "one_sided_95_lower_bound": nearest_rank(0.05),
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

    def check_phase(phase: str, main: dict[str, Any], candidate: dict[str, Any]) -> None:
        for metric in ("p95_ms", "peak_memory_bytes"):
            main_value = main.get(metric)
            candidate_value = candidate.get(metric)
            if not isinstance(main_value, (int, float)) or not isinstance(
                candidate_value, (int, float)
            ):
                reasons.append(f"{phase} {metric} is unavailable")
                continue
            if candidate_value > main_value * (1 + MAX_REGRESSION):
                reasons.append(f"{phase} {metric} regressed by more than 20%")

    main_measurements = performance.get("main", {})
    candidate_measurements = performance.get("candidate", {})
    main_splits = set(main_measurements) - {"warmed_query"}
    candidate_splits = set(candidate_measurements) - {"warmed_query"}
    if "dev" not in main_splits | candidate_splits:
        reasons.append("development fresh-process performance is unavailable")
    for split in sorted(main_splits | candidate_splits):
        main_split = main_measurements.get(split)
        candidate_split = candidate_measurements.get(split)
        if not isinstance(main_split, dict) or not isinstance(candidate_split, dict):
            reasons.append(f"{split} fresh-process performance is unavailable")
            continue
        check_phase(
            f"{split} fresh-process",
            main_split.get("fresh_process", {}),
            candidate_split.get("fresh_process", {}),
        )
    check_phase(
        "warmed-query",
        main_measurements.get("warmed_query", {}),
        candidate_measurements.get("warmed_query", {}),
    )
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
    if bootstrap["one_sided_95_lower_bound"] <= 0:
        reasons.append("paired bootstrap one-sided 95% lower bound is not above zero")
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


def evaluate_independent_holdout_gate(
    quality: dict[str, Any],
    bootstrap: dict[str, Any],
    performance: dict[str, Any],
    execution: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Require improvement on holdout itself; development cannot offset it."""
    main = quality["main"]
    candidate = quality["candidate"]
    reasons: list[str] = []
    success_at_1_gain = rate(candidate["success_at_1"]) - rate(
        main["success_at_1"]
    )
    if success_at_1_gain < MIN_SUCCESS_AT_1_GAIN:
        reasons.append("independent holdout Success@1 gain is below five percentage points")

    guarded_metrics = (
        "success_at_3",
        "incorrect_answered_tasks",
        "false_answers_on_unanswerable",
    )
    for metric in guarded_metrics:
        candidate_rate = rate(candidate[metric])
        main_rate = rate(main[metric])
        regressed = (
            candidate_rate < main_rate
            if metric == "success_at_3"
            else candidate_rate > main_rate
        )
        if regressed:
            reasons.append(f"independent holdout {metric} regressed overall")

    for platform_name, value in quality["platform"].items():
        for metric in (
            "success_at_1",
            *guarded_metrics,
        ):
            candidate_rate = rate(value["candidate"][metric])
            main_rate = rate(value["main"][metric])
            regressed = (
                candidate_rate < main_rate
                if metric in {"success_at_1", "success_at_3"}
                else candidate_rate > main_rate
            )
            if regressed:
                reasons.append(
                    f"independent holdout {metric} regressed on platform {platform_name}"
                )

    if bootstrap["one_sided_95_lower_bound"] <= 0:
        reasons.append(
            "independent holdout paired bootstrap one-sided 95% lower bound is not above zero"
        )
    performance_passed, performance_reasons = performance_gate(performance)
    reasons.extend(performance_reasons)
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
        "success_at_1_gain": success_at_1_gain,
        "reasons": reasons,
        "thresholds": {
            "minimum_success_at_1_gain": MIN_SUCCESS_AT_1_GAIN,
            "holdout_success_at_1_bootstrap_lower_bound": "greater than zero",
            "success_at_1_platform_policy": "no regression on any platform",
            "success_at_3_platform_policy": "no regression on any platform",
            "incorrect_and_false_answer_policy": "no regression overall or on any platform",
            "performance_phase_max_regression": MAX_REGRESSION,
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
    stdout: str, index: ExampleIndex, task_platform: str
) -> tuple[tuple[DisplayIdentity, ...], tuple[dict[str, str], ...]]:
    allowed_platforms = eligible_result_platforms(task_platform)
    ids: list[DisplayIdentity] = []
    unmapped: list[dict[str, str]] = []
    for result in parse_displayed_results(stdout):
        matches_by_platform = {
            example_id
            for platform_name in allowed_platforms
            for example_id in index.get(
                (
                    normalize_page_command_text(result["page_command"], platform_name),
                    normalize_description_text(result["page_description"]),
                    normalize_description_text(result["description"]),
                    normalize_command_text(result["command"]),
                ),
                {},
            ).get(platform_name, ())
        }
        matches = tuple(sorted(matches_by_platform))
        if not matches:
            ids.append(None)
            unmapped.append(result)
        else:
            ids.append(matches)
    return tuple(ids), tuple(unmapped)


def format_display_identity(identity: Sequence[str] | None) -> str:
    if identity is None:
        return "unmapped"
    if len(identity) == 1:
        return identity[0]
    return "{" + " | ".join(identity) + "}"


def format_displayed_identities(
    identities: Sequence[Sequence[str] | None],
) -> str:
    return ", ".join(format_display_identity(identity) for identity in identities) or "none"


def run_cli(
    binary: Path,
    data_dir: Path,
    task: dict[str, Any],
    network_prefix: Sequence[str],
    timing_prefix: Sequence[str],
    *,
    index: ExampleIndex,
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
    displayed_id_candidates, unmapped = map_output_to_ids(
        stdout, index, task["platform"]
    )
    displayed_ids = tuple(
        identity[0] if identity is not None and len(identity) == 1 else None
        for identity in displayed_id_candidates
    )
    return CommandRun(
        displayed_example_ids=displayed_ids,
        displayed_example_id_candidates=displayed_id_candidates,
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
    index: ExampleIndex,
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
            result.displayed_example_id_candidates,
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
        f"- Evidence scope: `{report['protocol']['evidence_scope']}`",
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
        f"- Independent holdout freeze: `{report['inputs']['independent_holdout_freeze_id']}`",
        f"- Gate runner SHA-256: `{report['inputs']['gate_runner_sha256']}`",
        f"- Candidate bundle: `{report['inputs']['bundle']['bundle_id']}`",
        f"- Candidate bundle tree SHA-256: `{report['inputs']['bundle']['bundle_tree_sha256']}`",
        f"- Main data tree SHA-256: `{report['inputs']['main_data_dir_tree_sha256']}`",
        f"- Main database SHA-256: `{report['inputs']['input_compatibility']['main_database_sha256']}` (pinned evaluation baseline match: `{report['inputs']['input_compatibility']['main_database_matches_pinned_baseline']}`).",
        f"- Shared visible corpus: `{report['inputs']['input_compatibility']['visible_corpus_example_count']}` examples; SHA-256 `{report['inputs']['input_compatibility']['visible_corpus_examples_sha256']}`.",
        f"- Benchmark corpus: `{report['inputs']['benchmark_corpus_compatibility']['dev']['parser_version']}` at `{report['inputs']['benchmark_corpus_compatibility']['dev']['source_revision']}`; SHA-256 `{report['inputs']['benchmark_corpus_compatibility']['dev']['source_digest']}`.",
        f"- Matching model assets verified: `{report['inputs']['input_compatibility']['model_asset_count']}`.",
        f"- Dev dataset SHA-256: `{report['inputs']['dev_dataset_sha256']}`",
        f"- Holdout dataset SHA-256: `{report['inputs']['holdout_dataset_sha256']}`",
        f"- Candidate configuration: `{report['retrieval_configuration']['configuration_id']}`; "
        f"`{report['retrieval_configuration']['dense_recipe']}` text; "
        f"`{report['retrieval_configuration']['query_mode']}` queries; "
        f"top-{report['retrieval_configuration']['candidate_budget']}; "
        f"`{report['retrieval_configuration']['example_selection']}`; "
        f"ranking `{report['retrieval_configuration']['ranking']}`; "
        f"distance `<= {report['retrieval_configuration']['distance_cutoff']}`; "
        f"abstention `{report['retrieval_configuration']['abstention']}`; "
        f"fusion `{report['retrieval_configuration']['fusion']}`.",
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
    split_quality = {
        name: value
        for name, value in report["quality"].items()
        if name != "combined"
    }
    if len(split_quality) > 1:
        lines.extend(
            [
                "",
                "## Split-specific quality",
                "",
                "| Split | Metric | main | retrieval-v2 |",
                "| --- | --- | ---: | ---: |",
            ]
        )
        for split_name, split in split_quality.items():
            for metric in (
                "success_at_1",
                "success_at_3",
                "false_answers_on_unanswerable",
            ):
                lines.append(
                    f"| {split_name} | {metric_labels[metric]} | "
                    f"{pair(split['main'][metric])} | {pair(split['candidate'][metric])} |"
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
    for split_name in sorted(set(report["performance"]["main"]) - {"warmed_query"}):
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
            f"displayed IDs: `{format_displayed_identities(failure['displayed_example_id_candidates'])}`."
            for failure in failures
        )
    lines.extend(
        [
            "",
            "## Paired bootstrap",
            "",
            f"- Observed Success@1 gain: `{report['bootstrap']['observed_success_at_1_gain']:.4f}`.",
            f"- {report['bootstrap']['resamples']:,} resamples; seed `{report['bootstrap']['seed']}`.",
            f"- One-sided 95% lower bound: `{report['bootstrap']['one_sided_95_lower_bound']:.4f}`.",
            f"- 95% interval: `{report['bootstrap']['interval_95']['lower']:.4f}` to "
            f"`{report['bootstrap']['interval_95']['upper']:.4f}`.",
        ]
    )
    independent_bootstrap = report.get("independent_holdout_bootstrap")
    if independent_bootstrap is not None:
        lines.extend(
            [
                "",
                "## Independent holdout check",
                "",
                f"- Holdout Success@1 gain: `{independent_bootstrap['observed_success_at_1_gain']:.4f}`.",
                f"- One-sided 95% lower bound: `{independent_bootstrap['one_sided_95_lower_bound']:.4f}`.",
                f"- Independent holdout decision: **{report['independent_holdout_gate']['decision']}**.",
            ]
        )
    lines.extend(["", "## Gate conditions", ""])
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
        "--candidate-working-tree",
        action="store_true",
        help="build the current checkout, including uncommitted candidate changes",
    )
    result.add_argument(
        "--freeze-manifest",
        type=Path,
        default=ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json",
    )
    result.add_argument("--main-data-dir", type=Path, required=True)
    result.add_argument("--bundle", type=Path, required=True)
    result.add_argument(
        "--corpus-reference-ref", default=FROZEN_CORPUS_REFERENCE_REF
    )
    result.add_argument(
        "--corpus-reference-manifest",
        type=Path,
        default=ROOT / "tests/fixtures/tldr-evaluation-v2/manifest.json",
    )
    result.add_argument(
        "--corpus-reference-snapshot",
        type=Path,
        default=ROOT / "tests/fixtures/tldr-evaluation-v2",
    )
    result.add_argument(
        "--dev-dataset",
        type=Path,
        help="development dataset; defaults to the frozen evaluation-v2 dev split",
    )
    result.add_argument(
        "--allow-holdout",
        action="store_true",
        help="authorize reading the frozen holdout split",
    )
    result.add_argument(
        "--dev-only",
        action="store_true",
        help="dry-run the gate on the development split only; the report is "
        "verification evidence, not a release-gate decision",
    )
    result.add_argument(
        "--allow-custom-dev-dataset",
        action="store_true",
        help="validate the pinned schema-3 dev extension; requires --dev-only",
    )
    result.add_argument(
        "--custom-dev-manifest",
        type=Path,
        help="manifest for the pinned schema-3 development extension",
    )
    result.add_argument(
        "--candidate-config",
        type=Path,
        help="frozen retrieval configuration metadata for this candidate run",
    )
    result.add_argument(
        "--holdout-dataset",
        type=Path,
        help="optional explicit holdout path; a fresh freeze manifest pins this path",
    )
    result.add_argument(
        "--independent-holdout-manifest",
        type=Path,
        help="use the separately frozen fresh holdout; still requires --allow-holdout",
    )
    result.add_argument("--warmup-queries", type=int, default=5)
    result.add_argument("--warm-queries", type=int, default=30)
    result.add_argument("--output-json", type=Path, required=True)
    result.add_argument("--output-markdown", type=Path, required=True)
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.dev_only and (args.allow_holdout or args.independent_holdout_manifest is not None):
        raise ValueError("--dev-only excludes holdout access; drop holdout authorization options")
    if args.allow_custom_dev_dataset and not args.dev_only:
        raise ValueError("--allow-custom-dev-dataset requires --dev-only")
    if args.candidate_config is not None and not args.dev_only:
        raise ValueError("--candidate-config is limited to --dev-only experiments")
    if not args.dev_only and not args.allow_holdout:
        raise ValueError("--allow-holdout is required for the release gate")
    repo = args.repo_root.resolve()
    custom_dev_freeze: dict[str, Any] | None = None
    custom_dev_manifest_path: Path | None = None
    if args.allow_custom_dev_dataset:
        custom_dev_manifest_path = (
            args.custom_dev_manifest.resolve()
            if args.custom_dev_manifest is not None
            else ROOT / "tests/fixtures/evaluation/dev-only-extension-v1.manifest.json"
        )
        custom_dev_freeze, custom_dev_dataset_path = validate_custom_dev_freeze(
            custom_dev_manifest_path,
            args.dev_dataset,
            repo,
        )
        args.dev_dataset = custom_dev_dataset_path
    else:
        if args.custom_dev_manifest is not None:
            raise ValueError("--custom-dev-manifest requires --allow-custom-dev-dataset")
        if args.dev_dataset is None:
            args.dev_dataset = ROOT / "tests/fixtures/evaluation/frozen-dev-v2-expanded.json"
    args.dev_dataset = args.dev_dataset.resolve()
    bundle = args.bundle.resolve()
    main_data_dir = args.main_data_dir.resolve()
    freeze_manifest = args.freeze_manifest.resolve()
    independent_holdout_manifest_path = (
        args.independent_holdout_manifest.resolve()
        if args.independent_holdout_manifest is not None
        else None
    )
    holdout_freeze: dict[str, Any] | None = None
    holdout_dataset_path: Path | None = None
    if args.dev_only or independent_holdout_manifest_path is not None:
        validate_frozen_inputs(
            freeze_manifest,
            args.dev_dataset.resolve(),
            allow_custom_dev_dataset=args.allow_custom_dev_dataset,
        )
        if independent_holdout_manifest_path is not None:
            holdout_freeze, holdout_dataset_path = validate_fresh_holdout_freeze(
                independent_holdout_manifest_path,
                args.holdout_dataset,
                repo,
            )
    else:
        holdout_dataset_path = (
            args.holdout_dataset.resolve()
            if args.holdout_dataset is not None
            else ROOT / "tests/fixtures/evaluation/frozen-holdout-v2-expanded.json"
        )
        validate_frozen_inputs(
            freeze_manifest,
            args.dev_dataset.resolve(),
            holdout_dataset_path,
        )
    if not bundle.is_dir() or not (bundle / "manifest.json").is_file():
        raise ValueError("--bundle must be a validated matching bundle directory")
    if not main_data_dir.is_dir():
        raise ValueError("--main-data-dir must be a provisioned main CLI data directory")
    if not (main_data_dir / "commands.db").is_file():
        raise ValueError("--main-data-dir must contain commands.db")
    if not (main_data_dir / "models").is_dir():
        raise ValueError("--main-data-dir must contain the pinned models directory")
    input_compatibility = validate_main_data_compatibility(
        main_data_dir,
        bundle,
        allow_unpinned_main_database=args.dev_only,
    )
    if args.warmup_queries <= 0 or args.warm_queries <= 0:
        raise ValueError("warmup and measured query counts must be positive")

    freeze = load_json(freeze_manifest)
    dev = load_json(args.dev_dataset)
    if args.dev_only:
        # --dev-only must not read holdout labels at all; split identity is
        # asserted from the freeze manifest instead.
        holdout = None
        if args.allow_custom_dev_dataset:
            assert custom_dev_freeze is not None
            validate_custom_dev_dataset(dev, custom_dev_freeze)
    else:
        assert holdout_dataset_path is not None
        holdout = load_json(holdout_dataset_path)
        if holdout_freeze is not None:
            validate_fresh_holdout_dataset(holdout, holdout_freeze)
            validate_independent_dataset_pair(dev, holdout)
        else:
            evaluator.validate_dataset_pair(dev, holdout)
    candidate_corpus = {
        "parser_version": input_compatibility["candidate_parser_version"],
        "source_revision": input_compatibility["candidate_source_revision"],
        "source_digest": input_compatibility["candidate_source_digest"],
    }
    record_equivalence = None
    if candidate_corpus["parser_version"] != dev["corpus"]["parser_version"]:
        with tempfile.TemporaryDirectory(prefix="askman-corpus-equivalence-") as directory:
            record_equivalence = verify_corpus_record_equivalence(
                repo,
                dev,
                candidate_corpus,
                bundle,
                args.corpus_reference_manifest.resolve(),
                args.corpus_reference_snapshot.resolve(),
                args.corpus_reference_ref,
                Path(directory),
            )
    benchmark_corpus_compatibility = {
        "dev": validate_benchmark_corpus_compatibility(
            dev, candidate_corpus, "dev", record_equivalence
        )
    }
    if holdout is not None:
        benchmark_corpus_compatibility["holdout"] = (
            validate_benchmark_corpus_compatibility(
                holdout,
                candidate_corpus,
                "holdout",
                record_equivalence,
                allow_legacy_tldr_corpus_id=holdout_freeze is not None,
            )
        )
    if args.allow_custom_dev_dataset:
        connection = sqlite3.connect(bundle / "matching.db")
        try:
            evaluator.validate_labels(connection, dev["tasks"])
        finally:
            connection.close()
    candidate_configuration = DEFAULT_RETRIEVAL_CONFIGURATION
    if args.candidate_config is not None:
        candidate_configuration = load_json(args.candidate_config)
        if not isinstance(candidate_configuration.get("configuration_id"), str) or not candidate_configuration[
            "configuration_id"
        ].strip():
            raise ValueError("candidate configuration is missing its configuration_id")
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
            "candidate": build_binary(
                repo,
                args.candidate_ref,
                "candidate",
                scratch,
                working_tree=args.candidate_working_tree,
            ),
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
        main_outcomes_by_split: dict[str, list[dict[str, Any]]] = {}
        candidate_outcomes_by_split: dict[str, list[dict[str, Any]]] = {}
        performance: dict[str, Any] = {"main": {}, "candidate": {}}
        execution: dict[str, list[dict[str, Any]]] = {"main": [], "candidate": []}
        splits: tuple[tuple[str, dict[str, Any]], ...] = (
            (("dev", dev),) if args.dev_only else (("dev", dev), ("holdout", holdout))
        )
        for split_name, dataset in splits:
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
            main_outcomes_by_split[split_name] = main_outcomes
            candidate_outcomes_by_split[split_name] = candidate_outcomes
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
        independent_holdout_bootstrap = None
        independent_holdout_gate = None
        if not args.dev_only:
            holdout_tasks = holdout["tasks"]
            holdout_pairs = [
                (main, candidate)
                for task, main, candidate in zip(
                    holdout_tasks,
                    main_outcomes_by_split["holdout"],
                    candidate_outcomes_by_split["holdout"],
                )
                if task["answerable"]
            ]
            independent_holdout_bootstrap = paired_bootstrap(
                [main for main, _ in holdout_pairs],
                [candidate for _, candidate in holdout_pairs],
            )
            independent_holdout_gate = evaluate_independent_holdout_gate(
                quality["holdout"],
                independent_holdout_bootstrap,
                performance,
                execution,
            )
            if not independent_holdout_gate["passed"]:
                gate = {
                    **gate,
                    "passed": False,
                    "decision": "inconclusive",
                    "reasons": [
                        *gate["reasons"],
                        *independent_holdout_gate["reasons"],
                    ],
                }
        if args.dev_only:
            gate = {
                **gate,
                "passed": False,
                "decision": "inconclusive",
                "reasons": [
                    *gate["reasons"],
                    "dev-only evidence cannot make a release decision",
                ],
            }
        report = {
            "schema_version": 4,
            "evidence_id": "askman-main-vs-retrieval-v2-v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "complete",
            "protocol": {
                "primary_outcome": "user-visible displayed example IDs and abstentions",
                "development_and_holdout": not args.dev_only,
                "no_holdout_tuning": True,
                "query_network_policy": network_policy,
                "timing_policy": timing_policy,
                "setup_download_separate": True,
                "main_ref": args.main_ref,
                "candidate_ref": "working-tree" if args.candidate_working_tree else args.candidate_ref,
                "holdout_access_authorized": args.allow_holdout,
                "custom_dev_dataset": args.allow_custom_dev_dataset,
                "custom_dev_freeze_id": custom_dev_freeze.get("freeze_id")
                if custom_dev_freeze is not None
                else None,
                "candidate_configuration_id": candidate_configuration["configuration_id"],
                "holdout_freeze_id": holdout_freeze.get("freeze_id")
                if holdout_freeze is not None
                else freeze.get("freeze_id"),
                "evidence_scope": (
                    "custom-dev-only-exploration"
                    if args.allow_custom_dev_dataset
                    else "dev-only-verification"
                    if args.dev_only
                    else "release-gate"
                ),
            },
            "inputs": {
                "benchmark_id": freeze["benchmark_id"],
                "freeze_id": freeze["freeze_id"],
                "freeze_manifest_sha256": sha256_file(freeze_manifest),
                "independent_holdout_freeze_id": holdout_freeze.get("freeze_id")
                if holdout_freeze is not None
                else None,
                "independent_holdout_freeze_manifest_path": str(
                    independent_holdout_manifest_path
                )
                if independent_holdout_manifest_path is not None
                else None,
                "bundle": bundle_input,
                "main_data_dir_tree_sha256": sha256_tree(main_data_dir),
                "main_data_file_sha256": file_digests(main_data_dir),
                "bundle_file_sha256": file_digests(bundle),
                "input_compatibility": input_compatibility,
                "corpus_record_equivalence": record_equivalence,
                "benchmark_corpus_compatibility": benchmark_corpus_compatibility,
                "dev_dataset_sha256": sha256_file(args.dev_dataset),
                "dev_dataset_id": dev.get("dataset_id"),
                "dev_cohort_id": dev.get("cohort_id"),
                "dev_dataset_pinned_to_evaluation_v2": not args.allow_custom_dev_dataset,
                "custom_dev_freeze_manifest_path": str(custom_dev_manifest_path)
                if custom_dev_manifest_path is not None
                else None,
                "custom_dev_freeze_manifest_sha256": sha256_file(custom_dev_manifest_path)
                if custom_dev_manifest_path is not None
                else None,
                "candidate_config_path": str(args.candidate_config)
                if args.candidate_config is not None
                else None,
                "candidate_config_sha256": sha256_file(args.candidate_config)
                if args.candidate_config is not None
                else None,
                # In dev-only mode the holdout labels are never read; the
                # frozen digest from the freeze manifest is recorded instead.
                "holdout_dataset_sha256": freeze["splits"]["holdout"]["sha256"]
                if args.dev_only
                else sha256_file(holdout_dataset_path),
                "holdout_dataset_path": str(holdout_dataset_path)
                if holdout_dataset_path is not None
                else None,
                "independent_holdout_freeze_manifest_sha256": sha256_file(
                    independent_holdout_manifest_path
                )
                if independent_holdout_manifest_path is not None
                else None,
                "scorer_sha256": sha256_file(ROOT / "scripts/evaluate_retrieval.py"),
                "gate_runner_sha256": sha256_file(ROOT / "scripts/run_release_gate.py"),
            },
            "builds": builds,
            "quality": {**quality, "combined": combined},
            "bootstrap": bootstrap,
            "independent_holdout_bootstrap": independent_holdout_bootstrap,
            "independent_holdout_gate": independent_holdout_gate,
            "retrieval_configuration": candidate_configuration,
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
