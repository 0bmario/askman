#!/usr/bin/env python3
"""Evaluate retrieval against the frozen, source-backed milestone-1 tasks.

The runner deliberately talks to the validated SQLite artifact, not the
shipping Askman database.  It therefore has no network path and keeps task
questions, labels, and rationales outside the retrieval index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform as host_platform
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DATASET_SCHEMA_VERSION = 1
SCORER_VERSION = "task-scorer-v1"
KEYWORD_RETRIEVER_VERSION = "keyword-fts5-v1"
CURRENT_ADAPTER_VERSION = "current-askman-ranking-adapter-v1"
SUPPORTED_PLATFORMS = {"common", "linux", "osx", "windows"}
MAX_DISPLAYED_RESULTS = 3


@dataclass(frozen=True)
class Candidate:
    example_id: str
    page_id: str
    command: str
    page_description: str
    example_description: str
    source_path: str
    source_ref: str
    source_revision: str
    platform: str
    page_position: int
    example_position: int
    lexical_score: float


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


def normalized_tokens(question: str) -> list[str]:
    tokens = {
        token.lower()
        for token in re.split(r"[^A-Za-z0-9_]+", question)
        if token
    }
    return sorted(tokens)


def fts_query(question: str) -> str:
    tokens = normalized_tokens(question)
    if not tokens:
        raise ValueError("query contains no searchable tokens")
    return " AND ".join(f'"{token.replace(chr(34), chr(34) + chr(34))}"' for token in tokens)


def metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return dict(connection.execute("SELECT key, value FROM artifact_metadata"))


def selected_page_ids(connection: sqlite3.Connection, platform: str) -> set[str]:
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"unsupported platform: {platform}")
    rows = connection.execute(
        "SELECT page_id, page_name, platform FROM pages ORDER BY page_position"
    )
    pages = list(rows)
    names = {row[1] for row in pages}
    selected: set[str] = set()
    for name in names:
        target = next(
            (row for row in pages if row[1] == name and row[2] == platform), None
        )
        common = next(
            (row for row in pages if row[1] == name and row[2] == "common"), None
        )
        chosen = target or common
        if chosen:
            selected.add(chosen[0])
    return selected


def fetch_candidates(
    connection: sqlite3.Connection, question: str, platform: str
) -> list[Candidate]:
    page_ids = sorted(selected_page_ids(connection, platform))
    if not page_ids:
        return []
    placeholders = ",".join("?" for _ in page_ids)
    rows = connection.execute(
        f"""SELECT e.example_id, e.page_id, e.command, p.description, e.description,
                   p.source_path, p.source_ref, p.source_revision, p.platform,
                   p.page_position, e.position, bm25(example_lexical)
            FROM example_lexical
            JOIN examples AS e ON e.example_id = example_lexical.example_id
            JOIN pages AS p ON p.page_id = e.page_id
            WHERE example_lexical MATCH ? AND p.page_id IN ({placeholders})
            ORDER BY bm25(example_lexical), e.example_id""",
        (fts_query(question), *page_ids),
    )
    return [Candidate(*row) for row in rows]


def one_per_page(candidates: Iterable[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    result = []
    for candidate in candidates:
        if candidate.page_id in seen:
            continue
        seen.add(candidate.page_id)
        result.append(candidate)
    return result


def keyword_results(candidates: list[Candidate]) -> list[Candidate]:
    return one_per_page(candidates)[:MAX_DISPLAYED_RESULTS]


def current_adjustment(candidate: Candidate, raw_distance: float) -> float | None:
    """Adapt the current Rust ranking heuristics to lexical candidates.

    The released ranker receives MiniLM L2 distances.  This adapter preserves
    its filtering and command/domain multipliers while using a deterministic
    normalized FTS distance so both controlled baselines share one candidate
    pool.  It is intentionally not the historical-policy smoke run.
    """
    if raw_distance > 1.10:
        return None
    score = raw_distance
    description = candidate.page_description
    command = candidate.command
    if any(site in description for site in (
        "gnu.",
        "kernel.",
        "man7.",
        "manned.",
        "linux.",
        "man.openbsd",
        "man.freebsd",
        "greenwoodsoftware.",
    )):
        score *= 0.8
    if command == "grep" or (
        len(command) <= 3 and not command.startswith("q") and not command.startswith("z")
    ):
        score *= 0.67
    elif (
        "-" in command
        or command.startswith("q")
        or command.startswith("z")
        or (command.endswith("grep") and command != "grep")
        or command.endswith("all")
    ):
        score *= 1.33
    return score


def current_adapter_results(candidates: list[Candidate]) -> list[Candidate]:
    if not candidates:
        return []
    scores = [candidate.lexical_score for candidate in candidates]
    low, high = min(scores), max(scores)
    span = high - low
    by_command: dict[str, tuple[float, Candidate]] = {}
    for candidate in candidates:
        relative = 0.5 if span == 0 else (candidate.lexical_score - low) / span
        raw_distance = 0.5 + (relative * 0.6)
        adjusted = current_adjustment(candidate, raw_distance)
        if adjusted is None:
            continue
        previous = by_command.get(candidate.command)
        if previous is None or (adjusted, candidate.example_id) < (
            previous[0],
            previous[1].example_id,
        ):
            by_command[candidate.command] = (adjusted, candidate)
    ranked = sorted(
        by_command.values(), key=lambda item: (item[0], item[1].example_id)
    )
    return [candidate for _, candidate in ranked[:MAX_DISPLAYED_RESULTS]]


def score_task(
    task: dict[str, Any], displayed: list[Candidate], candidates: list[Candidate]
) -> dict[str, Any]:
    acceptable = set(task["acceptable_example_ids"])
    answerable = task["answerable"]
    displayed_ids = [candidate.example_id for candidate in displayed]
    candidate_ids = {candidate.example_id for candidate in candidates}
    hit_at_1 = bool(displayed_ids and displayed_ids[0] in acceptable)
    hit_at_3 = any(example_id in acceptable for example_id in displayed_ids[:3])
    candidate_hit = bool(acceptable & candidate_ids) if answerable else False
    answered = bool(displayed_ids)
    return {
        "task_id": task["id"],
        "displayed_example_ids": displayed_ids,
        "candidate_example_ids": [candidate.example_id for candidate in candidates],
        "success_at_1": hit_at_1 if answerable else False,
        "success_at_3": hit_at_3 if answerable else False,
        "candidate_recall": candidate_hit if answerable else None,
        "answered": answered,
        "incorrect_answer": answerable and answered and not hit_at_3,
        "false_answer": not answerable and answered,
    }


def summarize(tasks: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [task for task in tasks if task["answerable"]]
    unanswerable = [task for task in tasks if not task["answerable"]]
    by_id = {result["task_id"]: result for result in results}
    answerable_results = [by_id[task["id"]] for task in answerable]
    answered = [result for result in results if result["answered"]]
    return {
        "tasks": len(tasks),
        "answerable_tasks": len(answerable),
        "unanswerable_tasks": len(unanswerable),
        "success_at_1": {
            "count": sum(result["success_at_1"] for result in answerable_results),
            "denominator": len(answerable),
        },
        "success_at_3": {
            "count": sum(result["success_at_3"] for result in answerable_results),
            "denominator": len(answerable),
        },
        "candidate_recall": {
            "count": sum(result["candidate_recall"] for result in answerable_results),
            "denominator": len(answerable),
        },
        "coverage": {"count": len(answered), "denominator": len(tasks)},
        "incorrect_answered_tasks": {
            "count": sum(result["incorrect_answer"] for result in results),
            "denominator": len(answered),
        },
        "false_answers_on_unanswerable": {
            "count": sum(result["false_answer"] for result in results),
            "denominator": len(unanswerable),
        },
    }


def validate_dataset(dataset: dict[str, Any]) -> None:
    if dataset.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported evaluation dataset schema")
    if dataset.get("scorer_version") != SCORER_VERSION:
        raise ValueError("unsupported scorer version")
    tasks = dataset.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 60:
        raise ValueError("frozen dataset must contain exactly 60 tasks")
    splits = {task.get("split") for task in tasks}
    if splits != {"dev", "holdout"}:
        raise ValueError("dataset must contain dev and holdout splits")
    if sum(task["split"] == "dev" for task in tasks) != 30:
        raise ValueError("dataset must contain exactly 30 dev tasks")
    if sum(task["split"] == "holdout" for task in tasks) != 30:
        raise ValueError("dataset must contain exactly 30 holdout tasks")
    families: dict[str, set[str]] = {}
    for task in tasks:
        required = {"id", "split", "family", "question", "platform", "answerable", "acceptable_example_ids", "rationale"}
        if not required <= task.keys():
            raise ValueError(f"task {task.get('id')} is missing required labels")
        if task["platform"] not in SUPPORTED_PLATFORMS:
            raise ValueError(f"task {task['id']} has unsupported platform")
        if not task["answerable"] and task["acceptable_example_ids"]:
            raise ValueError(f"unanswerable task {task['id']} has acceptable IDs")
        if task["answerable"] and not task["acceptable_example_ids"]:
            raise ValueError(f"answerable task {task['id']} has no acceptable IDs")
        families.setdefault(task["family"], set()).add(task["split"])
    if any(len(splits) != 1 for splits in families.values()):
        raise ValueError("scenario families must not cross the dev/holdout split")


def validate_artifact(
    connection: sqlite3.Connection, dataset: dict[str, Any], manifest: Path | None
) -> dict[str, str]:
    actual = metadata(connection)
    frozen = dataset["corpus"]
    checks = {
        "artifact_kind": actual.get("artifact_kind"),
        "schema_version": actual.get("schema_version"),
        "parser_version": actual.get("parser_version"),
        "source_revision": actual.get("source_revision"),
        "source_digest": actual.get("source_digest"),
    }
    for key, expected in frozen.items():
        if key in {"manifest_sha256", "corpus_id"}:
            continue
        if checks.get(key) != expected:
            raise ValueError(
                f"frozen corpus mismatch for {key}: expected {expected}, got {checks.get(key)}; "
                "labels are invalid for this artifact"
            )
    actual_corpus_id = f"{checks['source_revision']}:{checks['source_digest']}"
    if frozen.get("corpus_id") != actual_corpus_id:
        raise ValueError("frozen corpus ID mismatch; migrate labels explicitly")
    if manifest is not None:
        actual_manifest_digest = sha256_file(manifest)
        if actual_manifest_digest != frozen["manifest_sha256"]:
            raise ValueError("frozen corpus manifest digest mismatch; migrate labels explicitly")
    elif frozen.get("manifest_sha256"):
        raise ValueError("--manifest is required to verify the frozen corpus selection")
    return checks


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_path = Path(args.dataset)
    dataset = load_json(dataset_path)
    validate_dataset(dataset)
    if args.split == "holdout" and not args.allow_holdout:
        raise ValueError("holdout labels require --allow-holdout")
    tasks = [task for task in dataset["tasks"] if task["split"] == args.split]
    with sqlite3.connect(args.artifact) as connection:
        frozen_artifact = validate_artifact(connection, dataset, Path(args.manifest) if args.manifest else None)
        results = []
        for task in tasks:
            candidates = fetch_candidates(connection, task["question"], task["platform"])
            if args.retriever == "keyword":
                displayed = keyword_results(candidates)
            else:
                displayed = current_adapter_results(candidates)
            results.append(score_task(task, displayed, candidates))
    report = {
        "dataset_id": dataset["dataset_id"],
        "dataset_schema_version": dataset["schema_version"],
        "scorer_version": dataset["scorer_version"],
        "split_id": dataset["split_id"],
        "split": args.split,
        "retriever": args.retriever,
        "retriever_version": KEYWORD_RETRIEVER_VERSION if args.retriever == "keyword" else CURRENT_ADAPTER_VERSION,
        "corpus": frozen_artifact,
        "historical_policy_smoke": "separate: scripts/smoke_offline.sh",
        "holdout_access": {
            "authorized": args.split != "holdout" or args.allow_holdout,
            "recorded": args.split == "holdout",
            "utc": datetime.now(timezone.utc).isoformat() if args.split == "holdout" else None,
        },
        "summary": summarize(tasks, results),
        "tasks": results,
    }
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--artifact", required=True, type=Path)
    result.add_argument("--dataset", required=True, type=Path)
    result.add_argument("--manifest", type=Path)
    result.add_argument("--split", choices=("dev", "holdout"), default="dev")
    result.add_argument("--allow-holdout", action="store_true")
    result.add_argument("--retriever", choices=("keyword", "current-adapter"), default="keyword")
    result.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run(args)
    except (OSError, sqlite3.Error, ValueError, json.JSONDecodeError) as error:
        print(f"evaluation failed: {error}", file=sys.stderr)
        return 2
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
