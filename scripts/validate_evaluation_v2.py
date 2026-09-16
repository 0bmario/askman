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
EXPECTED_SUPPORT_AUDIT_SCHEMA_VERSION = 2
LEGACY_MANIFEST_FREEZE_ID = "evaluation-v2-release-benchmark-v1"
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


def validate_dataset_freeze_id(
    manifest: dict[str, Any], dataset: dict[str, Any], split: str
) -> None:
    if (
        "freeze_id" not in dataset
        and manifest.get("freeze_id") == LEGACY_MANIFEST_FREEZE_ID
    ):
        return
    if dataset.get("freeze_id") != manifest.get("freeze_id"):
        raise ValueError(
            f"{split} dataset freeze ID mismatch with freeze manifest"
        )


def validate_support_audit(
    audit: dict[str, Any],
    development: dict[str, Any],
    holdout: dict[str, Any],
    intents: dict[str, Any] | None = None,
) -> None:
    """Verify every task label against its independently hand-audited support set."""
    if audit.get("schema_version") != EXPECTED_SUPPORT_AUDIT_SCHEMA_VERSION:
        raise ValueError("unsupported support-audit schema")
    families = audit.get("families")
    if not isinstance(families, dict):
        raise ValueError("support audit must declare family rules")
    task_support = audit.get("tasks")
    if not isinstance(task_support, dict):
        raise ValueError("support audit must declare task support records")
    tasks = development["tasks"] + holdout["tasks"]
    expected_families = {task["family"] for task in tasks}
    if set(families) != expected_families:
        raise ValueError("support audit families do not match the frozen tasks")
    expected_task_ids = {task["id"] for task in tasks}
    if set(task_support) != expected_task_ids:
        raise ValueError("support audit task records do not match the frozen tasks")
    intent_by_id = (
        {task["id"]: task for task in intents["tasks"]}
        if intents is not None
        else {}
    )
    for task in tasks:
        rule = families.get(task["family"])
        if not isinstance(rule, dict):
            raise ValueError(f"missing support audit rule for {task['family']}")
        if "acceptable_example_ids" in rule:
            raise ValueError(
                "support audit family rules must not carry task-level example IDs"
            )
        if task["platform"] != rule.get("platform"):
            raise ValueError(f"support audit platform mismatch for {task['id']}")
        if task["answerable"] != rule.get("answerable"):
            raise ValueError(f"support audit label mismatch for {task['id']}")
        support = task_support[task["id"]]
        if not isinstance(support, dict) or set(support) != {
            "acceptable_example_ids",
            "rationale",
        }:
            raise ValueError(f"support audit task record is incomplete for {task['id']}")
        expected_ids = support["acceptable_example_ids"]
        if task["acceptable_example_ids"] != expected_ids:
            raise ValueError(
                f"acceptable support mismatch for {task['id']}; "
                "labels must equal the hand-audited support set"
            )
        if task["rationale"] != support["rationale"]:
            raise ValueError(f"support audit rationale mismatch for {task['id']}")
        if rule.get("intent") is None or not str(rule["intent"]).strip():
            raise ValueError(f"support audit is missing the behavior intent for {task['id']}")
        if intents is not None and rule["intent"] != intent_by_id[task["id"]]["intent"]:
            raise ValueError(f"support audit intent mismatch for {task['id']}")
        if not isinstance(expected_ids, list):
            raise ValueError(f"support audit IDs are not a list for {task['id']}")
        if not isinstance(support["rationale"], str) or not support["rationale"].strip():
            raise ValueError(f"support audit rationale is empty for {task['id']}")
        if any(not EXAMPLE_ID.fullmatch(example_id) for example_id in expected_ids):
            raise ValueError(f"support audit has an unstable example ID for {task['id']}")


def validate_hand_checks(
    hand_checks: Any,
    provenance: Any,
    development: dict[str, Any],
    holdout: dict[str, Any],
    intents: dict[str, Any],
) -> None:
    """Verify evidence-bearing independent checks against frozen task labels."""
    if not isinstance(provenance, dict):
        raise ValueError("hand-check provenance is required")
    required_provenance = {"method", "independent", "inputs", "reviewed_at", "identity_recorded"}
    if not required_provenance <= provenance.keys():
        raise ValueError("hand-check provenance is incomplete")
    if not isinstance(provenance["method"], str) or not provenance["method"].strip():
        raise ValueError("hand-check provenance method is empty")
    if provenance["independent"] is not True:
        raise ValueError("hand-check provenance must identify an independent method")
    if provenance["identity_recorded"] is not False:
        raise ValueError("hand-check provenance must not fabricate an identity")
    if not isinstance(provenance["reviewed_at"], str) or not provenance["reviewed_at"].strip():
        raise ValueError("hand-check provenance date is empty")
    if not isinstance(provenance["inputs"], list) or not provenance["inputs"]:
        raise ValueError("hand-check provenance must list review inputs")
    if any(not isinstance(item, str) or not item.strip() for item in provenance["inputs"]):
        raise ValueError("hand-check provenance inputs must be non-empty strings")

    if not isinstance(hand_checks, list) or not hand_checks:
        raise ValueError("hand-check records are required")
    tasks = development["tasks"] + holdout["tasks"]
    task_by_id = {task["id"]: task for task in tasks}
    intent_by_id = {task["id"]: task for task in intents["tasks"]}
    expected_families = {task["family"] for task in tasks}
    seen_task_ids: set[str] = set()
    seen_families: set[str] = set()
    seen_platforms: set[str] = set()
    seen_splits: set[str] = set()
    seen_labels: set[bool] = set()
    required_evidence = {"platform", "behavior", "acceptable_support", "abstention"}
    for record in hand_checks:
        if not isinstance(record, dict) or set(record) != {"task_id", "evidence"}:
            raise ValueError("hand-check record must contain only task_id and evidence")
        task_id = record["task_id"]
        if task_id in seen_task_ids or task_id not in task_by_id:
            raise ValueError(f"hand-check task ID is duplicated or unknown: {task_id}")
        seen_task_ids.add(task_id)
        task = task_by_id[task_id]
        seen_families.add(task["family"])
        seen_platforms.add(task["platform"])
        seen_splits.add(task["split"])
        seen_labels.add(task["answerable"])
        evidence = record["evidence"]
        if not isinstance(evidence, dict) or set(evidence) != required_evidence:
            raise ValueError(f"hand-check evidence is incomplete for {task_id}")
        platform = evidence["platform"]
        if (
            not isinstance(platform, dict)
            or platform.get("result") != "match"
            or platform.get("observed_platform") != task["platform"]
        ):
            raise ValueError(f"hand-check platform evidence mismatch for {task_id}")
        behavior = evidence["behavior"]
        expected_intent = intent_by_id[task_id]["intent"]
        if (
            not isinstance(behavior, dict)
            or behavior.get("result") != "match"
            or behavior.get("observed_intent") != expected_intent
        ):
            raise ValueError(f"hand-check behavior evidence mismatch for {task_id}")
        support = evidence["acceptable_support"]
        if (
            not isinstance(support, dict)
            or support.get("result") != "match"
            or support.get("observed_example_ids") != task["acceptable_example_ids"]
        ):
            raise ValueError(f"hand-check acceptable support mismatch for {task_id}")
        abstention = evidence["abstention"]
        expected_abstention_result = "not_applicable" if task["answerable"] else "confirmed"
        if (
            not isinstance(abstention, dict)
            or abstention.get("result") != expected_abstention_result
            or abstention.get("observed_answerable") != task["answerable"]
        ):
            raise ValueError(f"hand-check abstention evidence mismatch for {task_id}")
        for dimension in required_evidence:
            item = evidence[dimension]
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("evidence"), str)
                or not item["evidence"].strip()
            ):
                raise ValueError(f"hand-check {dimension} evidence is empty for {task_id}")

    if seen_families != expected_families:
        raise ValueError("hand-check records do not cover every scenario family")
    if seen_platforms != {"common", "linux", "osx", "windows"}:
        raise ValueError("hand-check records do not cover every platform")
    if seen_splits != {"dev", "holdout"} or seen_labels != {True, False}:
        raise ValueError("hand-check records do not cover both splits and labels")


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
        validate_dataset_freeze_id(manifest, dataset, split)
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
    hand_checks = manifest.get("hand_checks")
    if hand_checks is not None:
        validate_hand_checks(
            hand_checks,
            manifest.get("hand_check_provenance"),
            datasets["dev"],
            datasets["holdout"],
            intents,
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
