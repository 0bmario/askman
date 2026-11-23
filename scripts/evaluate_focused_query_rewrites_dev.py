#!/usr/bin/env python3
"""Compare focused query rewrites on one frozen dev-only task set."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform as host_platform
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = ROOT / "scripts/evaluate_retrieval.py"
QUERY_MODES = (
    "focused-v1",
    "focused-extension-v2",
    "focused-cross-drive-v2",
    "focused-v2",
)
CANDIDATE_BUDGET = 8
DISPLAY_LIMIT = 3
DISTANCE_CUTOFF = 0.60
LEXICAL_OVERLAP_WEIGHT = 0.05
LEXICAL_STOP_WORDS = {
    "a", "an", "and", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "it", "of", "on", "or", "the", "to", "with", "your",
}


def platform_for_common_task() -> str:
    return {
        "Darwin": "osx",
        "Linux": "linux",
        "Windows": "windows",
    }.get(host_platform.system(), "linux")


def load_evaluator():
    spec = importlib.util.spec_from_file_location(
        "askman_focused_query_rewrite_evaluator", EVALUATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load evaluator {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EVALUATOR = load_evaluator()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def query_words(value: str) -> list[str]:
    result = []
    current = []
    for character in value.lower():
        if character.isascii() and character.isalnum():
            current.append(character)
        elif current:
            result.append("".join(current))
            current = []
    if current:
        result.append("".join(current))
    return result


def query_has_negation(query: str, tokens: Sequence[str]) -> bool:
    negations = {"avoid", "cannot", "never", "no", "not", "without"}
    contractions = (
        "can't", "can’t", "doesn't", "doesn’t", "don't", "don’t", "mustn't", "mustn’t",
        "shouldn't", "shouldn’t", "wouldn't", "wouldn’t", "won't", "won’t",
    )
    return bool(negations.intersection(tokens)) or any(item in query.lower() for item in contractions)


def excluded_command(tokens: Sequence[str], command: str) -> bool:
    negations = {"avoid", "avoiding", "except", "excluding", "not", "without"}
    connectors = {"a", "the", "use", "using"}
    contraction_prefixes = {
        "can", "didn", "doesn", "don", "mustn", "shouldn", "won", "wouldn",
    }
    for index, word in enumerate(tokens):
        if word in negations:
            remaining = tokens[index + 1 :]
            if command in remaining:
                before = remaining[: remaining.index(command)]
                if len(before) <= 3 and all(item in connectors for item in before):
                    return True
        if (
            index + 2 < len(tokens)
            and word in contraction_prefixes
            and tokens[index + 1] == "t"
        ):
            remaining = tokens[index + 2 :]
            if command in remaining:
                before = remaining[: remaining.index(command)]
                if len(before) <= 3 and all(item in connectors for item in before):
                    return True
    return False


def negates_action(tokens: Sequence[str], index: int) -> bool:
    negations = {"avoid", "cannot", "never", "no", "not", "without"}
    prefixes = {"can", "didn", "doesn", "don", "mustn", "shouldn", "won", "wouldn"}
    if index > 0 and tokens[index - 1] in negations:
        return True
    if index > 1 and tokens[index - 1] == "t" and tokens[index - 2] in prefixes:
        return True
    return (
        index > 2
        and tokens[index - 1] == "to"
        and tokens[index - 2] == "want"
        and (
            tokens[index - 3] == "not"
            or (index > 3 and tokens[index - 3] == "t" and tokens[index - 4] in prefixes)
        )
    )


def product_suppresses_query(query: str) -> bool:
    tokens = query_words(query)
    negated = query_has_negation(query, tokens)
    names_photo = any(item in tokens for item in ("photo", "picture", "image"))
    observes_metadata = any(
        item in tokens for item in ("display", "extract", "inspect", "print", "read", "show")
    )
    removes_metadata = any(
        item in tokens for item in ("clear", "delete", "erase", "purge", "remove", "scrub", "strip", "wipe")
    )
    names_exif = "exif" in tokens or (
        names_photo
        and observes_metadata
        and any(item in tokens for item in ("camera", "fields", "metadata", "tags"))
    )
    if names_exif and observes_metadata and not removes_metadata and negated:
        return True

    names_file = any(item in tokens for item in ("file", "files"))
    names_contents = any(item in tokens for item in ("content", "contents", "text"))
    names_stdout = "stdout" in tokens or any(
        tokens[index : index + 2] == ["standard", "output"]
        for index in range(len(tokens) - 1)
    )
    actions = {
        "display", "displaying", "print", "printing", "read", "reading", "show", "showing",
        "write", "writing",
    }
    if names_file and names_contents and names_stdout and any(
        token in actions and negates_action(tokens, index)
        for index, token in enumerate(tokens)
    ):
        return True
    return names_file and names_contents and names_stdout and excluded_command(tokens, "cat")


def lexical_terms(value: str) -> set[str]:
    tokens = query_words(value)
    return {token for token in tokens if token not in LEXICAL_STOP_WORDS}


def summarize_groups(
    tasks: Sequence[dict[str, Any]], outcomes: Sequence[dict[str, Any]], field: str
) -> dict[str, Any]:
    groups: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for task, outcome in zip(tasks, outcomes):
        key = str(task[field])
        group_tasks, group_outcomes = groups.setdefault(key, ([], []))
        group_tasks.append(task)
        group_outcomes.append(outcome)
    return {
        key: EVALUATOR.summarize(group_tasks, group_outcomes)
        for key, (group_tasks, group_outcomes) in sorted(groups.items())
    }


def score_mode(
    mode: str,
    tasks: Sequence[dict[str, Any]],
    pools: dict[str, list[Any]],
    page_commands: dict[str, str],
) -> dict[str, Any]:
    outcomes = []
    for task in tasks:
        pool = pools[task["id"]]
        query_tokens = lexical_terms(task["question"])
        eligible = [candidate for candidate in pool if candidate.ranking_score <= DISTANCE_CUTOFF]
        eligible.sort(
            key=lambda candidate: (
                candidate.ranking_score
                - LEXICAL_OVERLAP_WEIGHT
                * len(
                    query_tokens
                    & lexical_terms(
                        " ".join(
                            (
                                page_commands[candidate.page_id],
                                candidate.page_description,
                                candidate.example_description,
                                candidate.command,
                            )
                        )
                    )
                ),
                candidate.example_id,
            )
        )
        displayed = [] if product_suppresses_query(task["question"]) else eligible[:DISPLAY_LIMIT]
        outcomes.append(EVALUATOR.score_task(task, displayed, pool))
    return {
        "configuration": {
            "query_mode": mode,
            "dense_candidate_budget": CANDIDATE_BUDGET,
            "same_page_examples": "retained in top-k",
            "distance_cutoff": DISTANCE_CUTOFF,
            "ranking": "cosine distance minus 0.05 per shared query/candidate token",
            "display_limit": DISPLAY_LIMIT,
            "product_scoped_guards": "mirrored from src/dense.rs",
        },
        "summary": EVALUATOR.summarize(tasks, outcomes),
        "platform": summarize_groups(tasks, outcomes, "platform"),
        "family": summarize_groups(tasks, outcomes, "family"),
        "tasks": outcomes,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_path = args.dataset.resolve()
    manifest_path = args.manifest.resolve()
    artifact_path = args.artifact.resolve()
    model_cache = args.model_cache.resolve()
    helper = args.dense_helper.resolve()
    dataset = EVALUATOR.load_json(dataset_path)
    EVALUATOR.validate_dataset(dataset, "dev")
    tasks = dataset["tasks"]
    if not tasks or any(task["split"] != "dev" for task in tasks):
        raise ValueError("query rewrite experiments require a dev-only dataset")
    if dataset.get("cohort_id") != "askman-dev-extension-v1":
        raise ValueError("this frozen experiment is scoped to askman-dev-extension-v1")

    with sqlite3.connect(artifact_path) as connection:
        validation_dataset = {
            **dataset,
            "corpus": {
                key: value
                for key, value in dataset["corpus"].items()
                if key != "manifest_path"
            },
        }
        validation_dataset["corpus"]["schema_version"] = str(
            validation_dataset["corpus"]["schema_version"]
        )
        corpus = EVALUATOR.validate_artifact(
            connection, validation_dataset, manifest_path
        )
        EVALUATOR.validate_labels(connection, tasks)
        page_commands = dict(
            connection.execute("SELECT page_id, command FROM pages ORDER BY page_id")
        )
        inventory = connection.execute(
            """SELECT e.example_id, e.page_id, p.platform, p.command,
                      p.description, e.description, e.command
               FROM examples e JOIN pages p ON p.page_id = e.page_id
               ORDER BY e.example_id"""
        ).fetchall()
    if not page_commands:
        raise ValueError("candidate artifact has no source pages")

    variants = {}
    resources = {}
    for mode in QUERY_MODES:
        client = EVALUATOR.DenseClient(helper, artifact_path, model_cache, query_mode=mode)
        pools: dict[str, list[Any]] = {}
        try:
            for task in tasks:
                retrieval_platform = (
                    platform_for_common_task()
                    if task["platform"] == "common"
                    else task["platform"]
                )
                pools[task["id"]] = client.query(
                    task["question"],
                    retrieval_platform,
                    CANDIDATE_BUDGET,
                    include_same_page_examples=True,
                    platform_explicit=task["platform"] != "common",
                )
            resources[mode] = client.resources()
        finally:
            client.close()
        variants[mode] = score_mode(mode, tasks, pools, page_commands)

    inventory_sha256 = hashlib.sha256(
        json.dumps(inventory, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "report_kind": "askman-focused-query-rewrite-ablation-dev-v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "development only; exploratory rule selection; no holdout labels read",
        "holdout_access": {"authorized": False, "recorded": False},
        "dataset": {
            "path": str(dataset_path),
            "sha256": sha256_file(dataset_path),
            "cohort_id": dataset["cohort_id"],
            "task_count": len(tasks),
        },
        "corpus": {
            **corpus,
            "artifact_path": str(artifact_path),
            "artifact_sha256": sha256_file(artifact_path),
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "visible_example_count": len(inventory),
            "visible_inventory_sha256": inventory_sha256,
        },
        "helper": {"path": str(helper), "sha256": sha256_file(helper)},
        "resources": resources,
        "variants": variants,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--dataset", required=True, type=Path)
    result.add_argument("--manifest", required=True, type=Path)
    result.add_argument("--artifact", required=True, type=Path)
    result.add_argument("--dense-helper", required=True, type=Path)
    result.add_argument("--model-cache", required=True, type=Path)
    result.add_argument("--output", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        report = run(args)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (AttributeError, KeyError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as error:
        print(f"focused query rewrite evaluation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
