#!/usr/bin/env python3
"""Validate the frozen evaluation-v2 benchmark inputs and provenance."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest.json"
EXPECTED_MANIFEST_SCHEMA_VERSION = 1
EXPECTED_INTENT_SCHEMA_VERSION = 1
EXPECTED_DATASET_ID = "askman-evaluation-v2"
EXPECTED_SCORER_VERSION = "task-scorer-v1"
EXPECTED_SPLIT_ID = "scenario-family-split-v2"
EXPECTED_CORPUS_MANIFEST = ROOT / "tests/fixtures/tldr-full-corpus/manifest.json"
EXPECTED_INTENT_FIELDS = {"id", "split", "family", "source_category", "intent"}
EXAMPLE_ID = re.compile(r"example-[0-9a-f]{64}\Z")


SPEC = importlib.util.spec_from_file_location(
    "askman_evaluation_runner", ROOT / "scripts/evaluate_retrieval.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("failed to load the evaluation runner")
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


def resolve_path(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("benchmark manifest path must be a non-empty string")
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def validate_intents(
    intents: dict[str, Any], development: dict[str, Any], holdout: dict[str, Any]
) -> None:
    if intents.get("intent_schema_version") != EXPECTED_INTENT_SCHEMA_VERSION:
        raise ValueError("unsupported evaluation-v2 intent schema")
    if intents.get("dataset_id") != EXPECTED_DATASET_ID:
        raise ValueError("intent record has the wrong dataset ID")
    freeze = intents.get("intent_freeze")
    if not isinstance(freeze, dict) or freeze.get("authored_before_retrieval_inspection") is not True:
        raise ValueError("intent record must prove pre-retrieval authoring")
    if not freeze.get("id") or not freeze.get("authored_at") or not freeze.get("method"):
        raise ValueError("intent record is missing its authoring freeze metadata")

    source_catalog = intents.get("source_catalog")
    if not isinstance(source_catalog, list) or not source_catalog:
        raise ValueError("intent record must declare public source metadata")
    source_ids: set[str] = set()
    for source in source_catalog:
        if not isinstance(source, dict):
            raise ValueError("intent source catalog entries must be objects")
        required = {"id", "url", "license", "license_url", "use"}
        if not required <= source.keys():
            raise ValueError("intent source catalog entry is incomplete")
        source_id = source["id"]
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("intent source catalog IDs must be non-empty")
        source_ids.add(source_id)
        if not all(
            isinstance(source[field], str) and source[field]
            for field in required - {"id"}
        ):
            raise ValueError("intent source catalog values must be non-empty strings")
    if "tldr-pages" not in source_ids:
        raise ValueError("intent record must identify the pinned tldr-pages source")

    categories = intents.get("source_categories")
    if not isinstance(categories, dict) or not categories:
        raise ValueError("intent record must declare source categories")
    if not all(
        isinstance(category, str)
        and category
        and isinstance(description, str)
        and description
        for category, description in categories.items()
    ):
        raise ValueError("intent source categories must have non-empty descriptions")

    intent_tasks = intents.get("tasks")
    if not isinstance(intent_tasks, list) or len(intent_tasks) != 120:
        raise ValueError("evaluation-v2 intent record must contain exactly 120 tasks")
    label_tasks = development["tasks"] + holdout["tasks"]
    expected_by_id = {task["id"]: task for task in label_tasks}
    seen_ids: set[str] = set()
    for task in intent_tasks:
        if not isinstance(task, dict) or set(task) != EXPECTED_INTENT_FIELDS:
            raise ValueError(
                f"intent task fields must be exactly {sorted(EXPECTED_INTENT_FIELDS)}"
            )
        task_id = task["id"]
        if not isinstance(task_id, str) or not task_id or task_id in seen_ids:
            raise ValueError("intent task IDs must be unique and non-empty")
        seen_ids.add(task_id)
        if task_id not in expected_by_id:
            raise ValueError(f"intent record has no matching label task: {task_id}")
        label = expected_by_id[task_id]
        if task["split"] != label["split"] or task["family"] != label["family"]:
            raise ValueError(f"intent split/family mismatch for {task_id}")
        if task["source_category"] not in categories:
            raise ValueError(f"intent task has an unknown source category: {task_id}")
        if not isinstance(task["intent"], str) or not task["intent"].strip():
            raise ValueError(f"intent task has an empty normalized intent: {task_id}")
    if seen_ids != set(expected_by_id):
        raise ValueError("intent and label task IDs do not match")


def validate_family_intents(
    intents: dict[str, Any], development: dict[str, Any], holdout: dict[str, Any]
) -> None:
    """Require one platform/label/source intent per five-task family."""
    intent_by_id = {task["id"]: task for task in intents["tasks"]}
    signatures: dict[str, set[tuple[Any, ...]]] = {}
    for task in development["tasks"] + holdout["tasks"]:
        intent = intent_by_id[task["id"]]
        signature = (
            task["platform"],
            task["answerable"],
            intent["source_category"],
            intent["intent"],
        )
        signatures.setdefault(task["family"], set()).add(signature)
    mixed = [family for family, values in signatures.items() if len(values) != 1]
    if mixed:
        raise ValueError(
            "families must contain one exact platform/label/intent: "
            + ", ".join(sorted(mixed))
        )


def validate_support_audit(
    audit: dict[str, Any],
    development: dict[str, Any],
    holdout: dict[str, Any],
    intents: dict[str, Any] | None = None,
) -> None:
    """Verify every task label against its independently hand-audited support set."""
    if audit.get("schema_version") != 1:
        raise ValueError("unsupported support-audit schema")
    families = audit.get("families")
    if not isinstance(families, dict):
        raise ValueError("support audit must declare family rules")
    tasks = development["tasks"] + holdout["tasks"]
    expected_families = {task["family"] for task in tasks}
    if set(families) != expected_families:
        raise ValueError("support audit families do not match the frozen tasks")
    intent_by_id = (
        {task["id"]: task for task in intents["tasks"]}
        if intents is not None
        else {}
    )
    for task in tasks:
        rule = families.get(task["family"])
        if not isinstance(rule, dict):
            raise ValueError(f"missing support audit rule for {task['family']}")
        if task["platform"] != rule.get("platform"):
            raise ValueError(f"support audit platform mismatch for {task['id']}")
        if task["answerable"] != rule.get("answerable"):
            raise ValueError(f"support audit label mismatch for {task['id']}")
        expected_ids = rule.get("acceptable_example_ids")
        if task["acceptable_example_ids"] != expected_ids:
            raise ValueError(
                f"acceptable support mismatch for {task['id']}; "
                "labels must equal the hand-audited support set"
            )
        if rule.get("intent") is None or not str(rule["intent"]).strip():
            raise ValueError(f"support audit is missing the behavior intent for {task['id']}")
        if intents is not None and rule["intent"] != intent_by_id[task["id"]]["intent"]:
            raise ValueError(f"support audit intent mismatch for {task['id']}")
        if any(not EXAMPLE_ID.fullmatch(example_id) for example_id in expected_ids):
            raise ValueError(f"support audit has an unstable example ID for {task['id']}")


def validate_manifest(manifest_path: Path) -> None:
    manifest = RUNNER.load_json(manifest_path)
    if manifest.get("schema_version") != EXPECTED_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported evaluation-v2 freeze manifest schema")
    if manifest.get("benchmark_id") != EXPECTED_DATASET_ID:
        raise ValueError("freeze manifest has the wrong benchmark ID")
    if manifest.get("dataset_schema_version") != 2:
        raise ValueError("freeze manifest must pin dataset schema 2")
    if manifest.get("scorer_version") != EXPECTED_SCORER_VERSION:
        raise ValueError("freeze manifest has the wrong scorer version")
    if manifest.get("split_id") != EXPECTED_SPLIT_ID:
        raise ValueError("freeze manifest has the wrong split ID")
    if manifest.get("split_policy") != RUNNER.EVALUATION_V2_SPLIT_POLICY:
        raise ValueError("freeze manifest has the wrong split policy")
    if not manifest.get("frozen_at") or not manifest.get("freeze_id"):
        raise ValueError("freeze manifest is missing freeze metadata")

    scorer = manifest.get("scorer")
    if not isinstance(scorer, dict) or scorer.get("version") != EXPECTED_SCORER_VERSION:
        raise ValueError("freeze manifest is missing scorer metadata")
    scorer_path = resolve_path(scorer.get("implementation"))
    if RUNNER.sha256_file(scorer_path) != scorer.get("sha256"):
        raise ValueError("scorer implementation digest does not match the freeze manifest")

    corpus = manifest.get("corpus")
    if not isinstance(corpus, dict):
        raise ValueError("freeze manifest is missing corpus identity")
    corpus_manifest_value = manifest.get("corpus_manifest")
    corpus_manifest_path = (
        resolve_path(corpus_manifest_value)
        if corpus_manifest_value is not None
        else EXPECTED_CORPUS_MANIFEST
    )
    source_manifest = RUNNER.load_json(corpus_manifest_path)
    actual_manifest_digest = RUNNER.sha256_file(corpus_manifest_path)
    source = source_manifest.get("source", {})
    expected_source = {
        "source_revision": source.get("revision"),
        "source_digest": source.get("digest"),
        "manifest_sha256": actual_manifest_digest,
    }
    for field, expected in expected_source.items():
        if corpus.get(field) != expected:
            raise ValueError(f"freeze manifest corpus mismatch for {field}")

    splits = manifest.get("splits")
    if not isinstance(splits, dict) or set(splits) != {"dev", "holdout"}:
        raise ValueError("freeze manifest must declare dev and holdout inputs")
    datasets: dict[str, dict[str, Any]] = {}
    paths: set[Path] = set()
    for split, expected_counts in {"dev": (30, 30), "holdout": (30, 30)}.items():
        entry = splits[split]
        if not isinstance(entry, dict):
            raise ValueError(f"freeze manifest {split} entry must be an object")
        path = resolve_path(entry.get("path"))
        if path in paths:
            raise ValueError("development and holdout inputs must be separate files")
        paths.add(path)
        if RUNNER.sha256_file(path) != entry.get("sha256"):
            raise ValueError(f"{split} dataset digest does not match the freeze manifest")
        dataset = RUNNER.load_json(path)
        RUNNER.validate_dataset(dataset, split)
        if dataset.get("split_policy") != manifest.get("split_policy"):
            raise ValueError(f"{split} dataset split policy differs from freeze manifest")
        if dataset.get("corpus") != corpus:
            raise ValueError(f"{split} dataset corpus identity differs from freeze manifest")
        if dataset.get("provenance") != manifest.get("provenance"):
            raise ValueError(f"{split} dataset provenance differs from freeze manifest")
        if (
            dataset["answerable_task_count"],
            dataset["unanswerable_task_count"],
        ) != expected_counts:
            raise ValueError(f"{split} dataset label balance is not 30/30")
        for task in dataset["tasks"]:
            if any(
                not EXAMPLE_ID.fullmatch(example_id)
                for example_id in task["acceptable_example_ids"]
            ):
                raise ValueError(
                    f"{split} task has an unstable acceptable example ID: {task['id']}"
                )
        datasets[split] = dataset

    RUNNER.validate_dataset_pair(datasets["dev"], datasets["holdout"])

    provenance_file = manifest.get("provenance_file")
    if not isinstance(provenance_file, dict):
        raise ValueError("freeze manifest is missing provenance file metadata")
    intent_path = resolve_path(provenance_file.get("path"))
    if RUNNER.sha256_file(intent_path) != provenance_file.get("sha256"):
        raise ValueError("intent provenance digest does not match the freeze manifest")
    intents = RUNNER.load_json(intent_path)
    validate_intents(intents, datasets["dev"], datasets["holdout"])
    validate_family_intents(intents, datasets["dev"], datasets["holdout"])
    support_audit = manifest.get("support_audit")
    if support_audit is not None:
        validate_support_audit(
            support_audit, datasets["dev"], datasets["holdout"], intents
        )


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return argument_parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        validate_manifest(args.manifest)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"evaluation-v2 validation failed: {error}", file=sys.stderr)
        return 2
    print(f"valid evaluation-v2 benchmark: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
