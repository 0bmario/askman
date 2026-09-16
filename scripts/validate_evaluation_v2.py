#!/usr/bin/env python3
"""Validate the frozen evaluation-v2 benchmark inputs and provenance."""

from __future__ import annotations

import argparse
import hashlib
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
EXPECTED_SUPPORT_CATALOG_SCHEMA_VERSION = 1
LEGACY_MANIFEST_FREEZE_ID = "evaluation-v2-release-benchmark-v1"
EXAMPLE_ID = re.compile(r"example-[0-9a-f]{64}\Z")
QUESTION_TOKEN = re.compile(r"[a-z0-9]+")


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


def normalize_question(question: str) -> str:
    return " ".join(QUESTION_TOKEN.findall(question.casefold()))


def deterministic_id(kind: str, fields: list[str]) -> str:
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


def expected_example_id(
    source_manifest: dict[str, Any], source_path: str, source_position: int
) -> str:
    path_parts = Path(source_path).parts
    platform = path_parts[1]
    language = source_manifest["language"]
    source_revision = source_manifest["source"]["revision"]
    page_id = deterministic_id(
        "page", [source_revision, source_path, platform, language]
    )
    return deterministic_id("example", [page_id, str(source_position)])


def validate_split_question_disjointness(
    development: dict[str, Any], holdout: dict[str, Any]
) -> None:
    development_questions: dict[str, list[str]] = {}
    holdout_questions: dict[str, list[str]] = {}
    for task in development["tasks"]:
        development_questions.setdefault(normalize_question(task["question"]), []).append(
            task["id"]
        )
    for task in holdout["tasks"]:
        holdout_questions.setdefault(normalize_question(task["question"]), []).append(
            task["id"]
        )
    overlapping_questions = sorted(
        set(development_questions).intersection(holdout_questions)
    )
    if overlapping_questions:
        collisions = "; ".join(
            f"{question}: {development_questions[question]} vs {holdout_questions[question]}"
            for question in overlapping_questions
        )
        raise ValueError(
            "dev and holdout questions overlap after normalization: " + collisions
        )


def validate_dataset_freeze_id(
    manifest: dict[str, Any], dataset: dict[str, Any], split: str
) -> None:
    legacy_dataset_identity_is_absent = (
        "freeze_id" not in dataset
        and manifest.get("freeze_id") == LEGACY_MANIFEST_FREEZE_ID
    )
    if legacy_dataset_identity_is_absent:
        return
    if dataset.get("freeze_id") != manifest.get("freeze_id"):
        raise ValueError(
            f"{split} dataset freeze ID mismatch with freeze manifest"
        )


def validate_support_catalog(
    catalog: dict[str, Any],
    manifest: dict[str, Any],
    source_manifest: dict[str, Any],
    development: dict[str, Any],
    holdout: dict[str, Any],
) -> None:
    """Validate the pinned, hand-audited example-to-behavior ledger."""
    if catalog.get("schema_version") != EXPECTED_SUPPORT_CATALOG_SCHEMA_VERSION:
        raise ValueError("unsupported support-catalog schema")
    if catalog.get("dataset_id") != manifest.get("benchmark_id"):
        raise ValueError("support catalog has the wrong dataset ID")
    if catalog.get("corpus") != manifest.get("corpus"):
        raise ValueError("support catalog corpus identity differs from freeze manifest")
    if catalog.get("source_manifest_sha256") != manifest["corpus"]["manifest_sha256"]:
        raise ValueError("support catalog is not pinned to the freeze corpus manifest")

    audit = catalog.get("hand_audit")
    required_audit_fields = {
        "method",
        "independent",
        "reviewed_at",
        "identity_recorded",
        "inputs",
        "limitations",
    }
    audit_is_complete = isinstance(audit, dict) and required_audit_fields <= audit.keys()
    if not audit_is_complete:
        raise ValueError("support catalog hand-audit provenance is incomplete")
    method_is_recorded = isinstance(audit["method"], str) and bool(audit["method"].strip())
    independent_method_is_declared = audit["independent"] is True
    if not method_is_recorded:
        raise ValueError("support catalog hand-audit method is empty")
    if not independent_method_is_declared:
        raise ValueError("support catalog must record an independent hand-audit method")
    identity_is_omitted = audit["identity_recorded"] is False
    if not identity_is_omitted:
        raise ValueError("support catalog must not fabricate a reviewer identity")
    reviewed_at_is_recorded = (
        isinstance(audit["reviewed_at"], str) and bool(audit["reviewed_at"].strip())
    )
    limitations_are_recorded = (
        isinstance(audit["limitations"], str) and bool(audit["limitations"].strip())
    )
    if not reviewed_at_is_recorded:
        raise ValueError("support catalog hand-audit date is empty")
    if not limitations_are_recorded:
        raise ValueError("support catalog hand-audit limitations are empty")
    audit_inputs_are_recorded = (
        isinstance(audit["inputs"], list)
        and bool(audit["inputs"])
        and all(isinstance(item, str) and item.strip() for item in audit["inputs"])
    )
    if not audit_inputs_are_recorded:
        raise ValueError("support catalog hand-audit inputs are incomplete")

    entries = catalog.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("support catalog must declare example entries")
    answerable_tasks = [
        task
        for task in development["tasks"] + holdout["tasks"]
        if task["answerable"]
    ]
    expected_example_ids = {
        example_id
        for task in answerable_tasks
        for example_id in task["acceptable_example_ids"]
    }
    if set(entries) != expected_example_ids:
        raise ValueError(
            "support catalog entries must cover exactly the answerable example IDs"
        )
    pinned_source_paths = set(source_manifest.get("files", []))
    required_entry_fields = {
        "source_path",
        "source_line",
        "source_position",
        "section",
        "canonical_behavior",
    }
    for example_id, entry in entries.items():
        if not EXAMPLE_ID.fullmatch(example_id):
            raise ValueError(f"support catalog has an unstable example ID: {example_id}")
        entry_is_complete = (
            isinstance(entry, dict) and set(entry) == required_entry_fields
        )
        if not entry_is_complete:
            raise ValueError(f"support catalog entry is incomplete: {example_id}")
        source_path = entry["source_path"]
        source_path_is_pinned = (
            isinstance(source_path, str)
            and source_path in pinned_source_paths
            and (ROOT / "tests/fixtures/tldr-evaluation-v2" / source_path).is_file()
        )
        if not source_path_is_pinned:
            raise ValueError(f"support catalog source path is not pinned: {example_id}")
        source_line = entry["source_line"]
        source_file = ROOT / "tests/fixtures/tldr-evaluation-v2" / source_path
        source_lines = source_file.read_text(encoding="utf-8").splitlines()
        source_line_is_valid = (
            isinstance(source_line, int)
            and not isinstance(source_line, bool)
            and 1
            <= source_line
            <= len(source_lines)
        )
        if not source_line_is_valid:
            raise ValueError(f"support catalog source line is invalid: {example_id}")
        source_position = entry["source_position"]
        source_position_is_valid = (
            isinstance(source_position, int)
            and not isinstance(source_position, bool)
            and source_position > 0
        )
        if not source_position_is_valid:
            raise ValueError(f"support catalog source position is invalid: {example_id}")
        section_is_recorded = (
            isinstance(entry["section"], str) and bool(entry["section"].strip())
        )
        source_section_line = next(
            (
                line_number
                for line_number in range(source_line - 2, -1, -1)
                if source_lines[line_number].strip().startswith("- ")
            ),
            None,
        ) if source_line_is_valid else None
        source_command_is_at_source_line = (
            source_line_is_valid
            and source_lines[source_line - 1].strip().startswith("`")
            and source_lines[source_line - 1].strip().endswith("`")
        )
        section_is_before_source_line = (
            source_section_line is not None
            and section_is_recorded
            and source_lines[source_section_line].strip() == f"- {entry['section']}"
        )
        behavior_is_recorded = (
            isinstance(entry["canonical_behavior"], str)
            and bool(entry["canonical_behavior"].strip())
        )
        if not source_command_is_at_source_line:
            raise ValueError(f"support catalog source line is not an example command: {example_id}")
        if not section_is_before_source_line:
            raise ValueError(f"support catalog source section is not pinned: {example_id}")
        source_position_from_page = sum(
            line.strip().startswith("- ")
            for line in source_lines[: source_section_line + 1]
        )
        source_position_matches = source_position == source_position_from_page
        if not source_position_matches:
            raise ValueError(f"support catalog source position mismatch: {example_id}")
        stable_id_matches_source = (
            example_id
            == expected_example_id(source_manifest, source_path, source_position)
        )
        if not stable_id_matches_source:
            raise ValueError(f"support catalog example ID is not linked to its source: {example_id}")
        catalog_evidence_is_incomplete = not section_is_recorded or not behavior_is_recorded
        if catalog_evidence_is_incomplete:
            raise ValueError(f"support catalog evidence is incomplete: {example_id}")


def validate_support_audit(
    audit: dict[str, Any],
    development: dict[str, Any],
    holdout: dict[str, Any],
    intents: dict[str, Any],
    support_catalog: dict[str, Any],
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
    intent_by_id = {task["id"]: task for task in intents["tasks"]}
    catalog_entries = support_catalog.get("entries")
    if not isinstance(catalog_entries, dict):
        raise ValueError("support catalog must declare example entries")
    for task in tasks:
        rule = families.get(task["family"])
        if not isinstance(rule, dict):
            raise ValueError(f"missing support audit rule for {task['family']}")
        family_rule_has_task_ids = "acceptable_example_ids" in rule
        if family_rule_has_task_ids:
            raise ValueError(
                "support audit family rules must not carry task-level example IDs"
            )
        if task["platform"] != rule.get("platform"):
            raise ValueError(f"support audit platform mismatch for {task['id']}")
        if task["answerable"] != rule.get("answerable"):
            raise ValueError(f"support audit label mismatch for {task['id']}")
        support = task_support[task["id"]]
        support_record_is_complete = isinstance(support, dict) and set(support) == {
            "acceptable_example_ids",
            "rationale",
        }
        if not support_record_is_complete:
            raise ValueError(f"support audit task record is incomplete for {task['id']}")
        expected_ids = support["acceptable_example_ids"]
        support_matches_task = task["acceptable_example_ids"] == expected_ids
        if not support_matches_task:
            raise ValueError(
                f"acceptable support mismatch for {task['id']}; "
                "labels must equal the hand-audited support set"
            )
        if task["rationale"] != support["rationale"]:
            raise ValueError(f"support audit rationale mismatch for {task['id']}")
        family_intent_is_recorded = (
            isinstance(rule.get("intent"), str) and bool(rule["intent"].strip())
        )
        if not family_intent_is_recorded:
            raise ValueError(f"support audit is missing the behavior intent for {task['id']}")
        intent_matches_family = rule["intent"] == intent_by_id[task["id"]]["intent"]
        if not intent_matches_family:
            raise ValueError(f"support audit intent mismatch for {task['id']}")
        if not isinstance(expected_ids, list):
            raise ValueError(f"support audit IDs are not a list for {task['id']}")
        rationale_is_recorded = (
            isinstance(support["rationale"], str)
            and bool(support["rationale"].strip())
        )
        if not rationale_is_recorded:
            raise ValueError(f"support audit rationale is empty for {task['id']}")
        example_ids_are_stable = all(
            isinstance(example_id, str) and EXAMPLE_ID.fullmatch(example_id) is not None
            for example_id in expected_ids
        )
        if not example_ids_are_stable:
            raise ValueError(f"support audit has an unstable example ID for {task['id']}")
        unanswerable_task_has_support = not task["answerable"] and bool(expected_ids)
        if unanswerable_task_has_support:
            raise ValueError(f"unanswerable task {task['id']} has catalog support")
        for example_id in expected_ids:
            catalog_entry = catalog_entries.get(example_id)
            catalog_entry_is_recorded = isinstance(catalog_entry, dict)
            if not catalog_entry_is_recorded:
                raise ValueError(
                    f"support catalog is missing acceptable example {example_id}"
                )
            catalog_behavior_matches = (
                catalog_entry.get("canonical_behavior") == rule["intent"]
            )
            if not catalog_behavior_matches:
                raise ValueError(
                    f"support catalog behavior mismatch for {task['id']}: {example_id}"
                )


def validate_hand_check_citations(
    citations: Any,
    expected_example_ids: list[str],
    support_catalog: dict[str, Any],
    corpus: dict[str, Any],
    corpus_manifest_path: str,
    task_id: str,
    dimension: str,
) -> None:
    """Require hand-check citations to resolve to the pinned catalog or corpus."""
    required_citation_fields = {
        "catalog_entry_id",
        "source_path",
        "source_line",
        "section",
        "source_digest",
    }
    citations_are_recorded = isinstance(citations, list) and bool(citations)
    if not citations_are_recorded:
        raise ValueError(f"hand-check {dimension} citations are required for {task_id}")
    catalog_entries = support_catalog.get("entries")
    if not isinstance(catalog_entries, dict):
        raise ValueError("support catalog must declare example entries")
    expected_source_digest = corpus.get("source_digest")
    source_digest_is_pinned = (
        isinstance(expected_source_digest, str) and bool(expected_source_digest.strip())
    )
    if not source_digest_is_pinned:
        raise ValueError("hand-check citations require a pinned corpus source digest")
    expected_manifest_path = corpus_manifest_path
    catalog_citation_ids: list[str] = []
    manifest_citation_count = 0
    for citation in citations:
        citation_shape_is_valid = (
            isinstance(citation, dict) and set(citation) == required_citation_fields
        )
        if not citation_shape_is_valid:
            raise ValueError(f"hand-check {dimension} citation is incomplete for {task_id}")
        source_digest_matches = citation["source_digest"] == expected_source_digest
        if not source_digest_matches:
            raise ValueError(f"hand-check {dimension} citation digest mismatch for {task_id}")
        catalog_entry_id = citation["catalog_entry_id"]
        if catalog_entry_id is None:
            manifest_citation_is_valid = (
                citation["source_path"] == expected_manifest_path
                and citation["source_line"] is None
                and citation["section"] == "files"
                and resolve_path(expected_manifest_path).is_file()
            )
            if not manifest_citation_is_valid:
                raise ValueError(f"hand-check {dimension} citation does not resolve for {task_id}")
            manifest_citation_count += 1
            continue
        catalog_entry = catalog_entries.get(catalog_entry_id)
        catalog_entry_is_supported = isinstance(catalog_entry, dict)
        if not catalog_entry_is_supported:
            raise ValueError(
                f"hand-check {dimension} citation has unsupported catalog entry for {task_id}"
            )
        citation_matches_catalog = (
            citation["source_path"] == catalog_entry["source_path"]
            and citation["source_line"] == catalog_entry["source_line"]
            and citation["section"] == catalog_entry["section"]
        )
        if not citation_matches_catalog:
            raise ValueError(f"hand-check {dimension} citation does not match catalog for {task_id}")
        catalog_citation_ids.append(catalog_entry_id)

    citation_ids_are_unique = len(catalog_citation_ids) == len(set(catalog_citation_ids))
    expected_ids_are_cited = set(catalog_citation_ids) == set(expected_example_ids)
    manifest_citation_is_exclusive = (
        not expected_example_ids and manifest_citation_count > 0 and not catalog_citation_ids
    )
    catalog_citations_are_exclusive = (
        bool(expected_example_ids)
        and manifest_citation_count == 0
        and citation_ids_are_unique
        and expected_ids_are_cited
    )
    if not (manifest_citation_is_exclusive or catalog_citations_are_exclusive):
        raise ValueError(f"hand-check {dimension} citations do not match support for {task_id}")


def validate_hand_checks(
    hand_checks: Any,
    provenance: Any,
    development: dict[str, Any],
    holdout: dict[str, Any],
    intents: dict[str, Any],
    support_catalog: dict[str, Any],
    corpus: dict[str, Any],
    corpus_manifest_path: str,
) -> None:
    """Verify evidence-bearing independent checks against frozen task labels."""
    if not isinstance(provenance, dict):
        raise ValueError("hand-check provenance is required")
    required_provenance = {
        "method",
        "passes",
        "independent",
        "inputs",
        "reviewed_at",
        "identity_recorded",
    }
    provenance_fields_are_complete = required_provenance <= provenance.keys()
    if not provenance_fields_are_complete:
        raise ValueError("hand-check provenance is incomplete")
    method_is_recorded = isinstance(provenance["method"], str) and bool(
        provenance["method"].strip()
    )
    if not method_is_recorded:
        raise ValueError("hand-check provenance method is empty")
    review_passes_are_recorded = (
        isinstance(provenance["passes"], list)
        and len(provenance["passes"]) == 2
        and all(isinstance(item, str) and item.strip() for item in provenance["passes"])
    )
    if not review_passes_are_recorded:
        raise ValueError("hand-check provenance must record two independent review passes")
    independent_method_is_declared = provenance["independent"] is True
    if not independent_method_is_declared:
        raise ValueError("hand-check provenance must identify an independent method")
    reviewer_identity_is_omitted = provenance["identity_recorded"] is False
    if not reviewer_identity_is_omitted:
        raise ValueError("hand-check provenance must not fabricate an identity")
    review_date_is_recorded = isinstance(provenance["reviewed_at"], str) and bool(
        provenance["reviewed_at"].strip()
    )
    if not review_date_is_recorded:
        raise ValueError("hand-check provenance date is empty")
    review_inputs_are_recorded = (
        isinstance(provenance["inputs"], list) and bool(provenance["inputs"])
    )
    if not review_inputs_are_recorded:
        raise ValueError("hand-check provenance must list review inputs")
    review_inputs_are_valid = all(
        isinstance(item, str) and item.strip() for item in provenance["inputs"]
    )
    if not review_inputs_are_valid:
        raise ValueError("hand-check provenance inputs must be non-empty strings")

    hand_checks_are_recorded = isinstance(hand_checks, list) and bool(hand_checks)
    if not hand_checks_are_recorded:
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
        record_shape_is_valid = (
            isinstance(record, dict) and set(record) == {"task_id", "evidence"}
        )
        if not record_shape_is_valid:
            raise ValueError("hand-check record must contain only task_id and evidence")
        task_id = record["task_id"]
        task_id_is_duplicate_or_unknown = (
            task_id in seen_task_ids or task_id not in task_by_id
        )
        if task_id_is_duplicate_or_unknown:
            raise ValueError(f"hand-check task ID is duplicated or unknown: {task_id}")
        seen_task_ids.add(task_id)
        task = task_by_id[task_id]
        seen_families.add(task["family"])
        seen_platforms.add(task["platform"])
        seen_splits.add(task["split"])
        seen_labels.add(task["answerable"])
        evidence = record["evidence"]
        evidence_dimensions_are_complete = (
            isinstance(evidence, dict) and set(evidence) == required_evidence
        )
        if not evidence_dimensions_are_complete:
            raise ValueError(f"hand-check evidence is incomplete for {task_id}")
        platform = evidence["platform"]
        platform_evidence_is_inconsistent = (
            not isinstance(platform, dict)
            or platform.get("result") != "match"
            or platform.get("observed_platform") != task["platform"]
        )
        if platform_evidence_is_inconsistent:
            raise ValueError(f"hand-check platform evidence mismatch for {task_id}")
        behavior = evidence["behavior"]
        expected_intent = intent_by_id[task_id]["intent"]
        behavior_evidence_is_inconsistent = (
            not isinstance(behavior, dict)
            or behavior.get("result") != "match"
            or behavior.get("observed_intent") != expected_intent
        )
        if behavior_evidence_is_inconsistent:
            raise ValueError(f"hand-check behavior evidence mismatch for {task_id}")
        support = evidence["acceptable_support"]
        support_evidence_is_inconsistent = (
            not isinstance(support, dict)
            or support.get("result") != "match"
            or support.get("observed_example_ids") != task["acceptable_example_ids"]
        )
        if support_evidence_is_inconsistent:
            raise ValueError(f"hand-check acceptable support mismatch for {task_id}")
        validate_hand_check_citations(
            behavior.get("citations"),
            task["acceptable_example_ids"],
            support_catalog,
            corpus,
            corpus_manifest_path,
            task_id,
            "behavior",
        )
        validate_hand_check_citations(
            support.get("citations"),
            task["acceptable_example_ids"],
            support_catalog,
            corpus,
            corpus_manifest_path,
            task_id,
            "acceptable support",
        )
        abstention = evidence["abstention"]
        expected_abstention_result = "not_applicable" if task["answerable"] else "confirmed"
        abstention_evidence_is_inconsistent = (
            not isinstance(abstention, dict)
            or abstention.get("result") != expected_abstention_result
            or abstention.get("observed_answerable") != task["answerable"]
        )
        if abstention_evidence_is_inconsistent:
            raise ValueError(f"hand-check abstention evidence mismatch for {task_id}")
        for dimension in required_evidence:
            item = evidence[dimension]
            evidence_text_is_missing = (
                not isinstance(item, dict)
                or not isinstance(item.get("evidence"), str)
                or not item["evidence"].strip()
            )
            if evidence_text_is_missing:
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
    support_catalog = None
    if support_audit is not None:
        validate_split_question_disjointness(
            datasets["dev"], datasets["holdout"]
        )
        support_catalog_pin = manifest.get("support_catalog")
        required_catalog_pin_fields = {"path", "sha256", "catalog_id"}
        catalog_pin_is_complete = (
            isinstance(support_catalog_pin, dict)
            and required_catalog_pin_fields <= support_catalog_pin.keys()
        )
        if not catalog_pin_is_complete:
            raise ValueError("expanded freeze is missing support catalog metadata")
        support_catalog_path = resolve_path(support_catalog_pin.get("path"))
        if RUNNER.sha256_file(support_catalog_path) != support_catalog_pin.get("sha256"):
            raise ValueError("support catalog digest does not match the freeze manifest")
        support_catalog = RUNNER.load_json(support_catalog_path)
        if support_catalog.get("catalog_id") != support_catalog_pin["catalog_id"]:
            raise ValueError("support catalog ID does not match the freeze manifest")
        validate_support_catalog(
            support_catalog,
            manifest,
            source_manifest,
            datasets["dev"],
            datasets["holdout"],
        )
        validate_support_audit(
            support_audit,
            datasets["dev"],
            datasets["holdout"],
            intents,
            support_catalog,
        )
    hand_checks = manifest.get("hand_checks")
    if hand_checks is not None:
        if support_catalog is None:
            raise ValueError("hand checks require a support catalog")
        validate_hand_checks(
            hand_checks,
            manifest.get("hand_check_provenance"),
            datasets["dev"],
            datasets["holdout"],
            intents,
            support_catalog,
            corpus,
            corpus_manifest_value or str(corpus_manifest_path.relative_to(ROOT)),
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
