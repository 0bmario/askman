#!/usr/bin/env python3
"""Run fixed, dev-only retrieval ablations against identical source records.

The frozen evaluator and its historical configs remain unchanged. This runner
accepts only one dev dataset and compares dense representation, ranking,
selection, abstention, and lexical/dense fusion on that same task set.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sqlite3
import sys
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = ROOT / "scripts/evaluate_retrieval.py"
CANDIDATE_BUDGET = 8
LEGACY_MAIN_CANDIDATE_BUDGET = 7
DISPLAY_LIMIT = 3
LEXICAL_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "by", "for", "from", "in", "into",
    "is", "of", "on", "or", "the", "to", "with",
}
RRF_K = 60
KEYWORD_WEIGHT = 1.0
DENSE_WEIGHT = 1.05


def load_evaluator():
    spec = importlib.util.spec_from_file_location(
        "askman_controlled_dev_evaluator", EVALUATOR_PATH
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


def example_inventory(connection: sqlite3.Connection) -> list[tuple[Any, ...]]:
    rows = connection.execute(
        """SELECT e.example_id, e.page_id, p.platform, p.command,
                  p.description, e.description, e.command
           FROM examples AS e JOIN pages AS p ON p.page_id = e.page_id
           ORDER BY e.example_id"""
    )
    return list(rows)


def collect_dense(
    helper: Path,
    artifact: Path,
    model_cache: Path,
    tasks: Sequence[dict[str, Any]],
    *,
    query_mode: str,
    include_same_page_examples: bool,
    candidate_budget: int = CANDIDATE_BUDGET,
) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    client = EVALUATOR.DenseClient(
        helper, artifact, model_cache, query_mode=query_mode
    )
    results: dict[str, list[Any]] = {}
    try:
        for task in tasks:
            results[task["id"]] = client.query(
                task["question"],
                task["platform"],
                candidate_budget,
                include_same_page_examples=include_same_page_examples,
            )
        resources = client.resources()
    finally:
        client.close()
    return results, resources


def summarize_variant(
    name: str,
    tasks: Sequence[dict[str, Any]],
    outcomes: Sequence[dict[str, Any]],
    details: dict[str, Any],
) -> dict[str, Any]:
    by_id = {outcome["task_id"]: outcome for outcome in outcomes}
    return {
        "name": name,
        "configuration": details,
        "summary": EVALUATOR.summarize(tasks, outcomes),
        "platform": breakdown(tasks, by_id, "platform"),
        "family": breakdown(tasks, by_id, "family"),
        "tasks": outcomes,
    }


def breakdown(
    tasks: Sequence[dict[str, Any]],
    outcomes_by_id: dict[str, dict[str, Any]],
    field: str,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        groups.setdefault(str(task[field]), []).append(task)
    return {
        name: EVALUATOR.summarize(
            members, [outcomes_by_id[task["id"]] for task in members]
        )
        for name, members in sorted(groups.items())
    }


def score_dense(
    name: str,
    tasks: Sequence[dict[str, Any]],
    candidates_by_task: dict[str, list[Any]],
    *,
    distance_cutoff: float | None,
    legacy_preferences: bool = False,
    legacy_rank_strength: float = 0.0,
    target_platform_bias: float = 0.0,
    lexical_rerank_weight: float = 0.0,
    include_same_page_examples: bool = False,
) -> dict[str, Any]:
    outcomes = []
    for task in tasks:
        candidate_pool = list(candidates_by_task[task["id"]])
        eligible = [
            candidate
            for candidate in candidate_pool
            if distance_cutoff is None
            or (
                legacy_main_distance(candidate)
                if legacy_preferences
                else candidate.ranking_score
            )
            <= distance_cutoff
        ]
        if legacy_preferences:
            candidates = [
                replace(candidate, ranking_score=legacy_adjusted_distance(candidate))
                for candidate in eligible
            ]
            candidates.sort(key=lambda item: (item.ranking_score, item.example_id))
        elif legacy_rank_strength > 0.0:
            candidates = [
                replace(
                    candidate,
                    ranking_score=partially_adjusted_distance(
                        candidate, legacy_rank_strength
                    ),
                )
                for candidate in eligible
            ]
            candidates.sort(key=lambda item: (item.ranking_score, item.example_id))
        elif target_platform_bias > 0.0 and task["platform"] != "common":
            candidates = sorted(
                eligible,
                key=lambda item: (
                    item.ranking_score
                    - (target_platform_bias if item.platform == task["platform"] else 0.0),
                    item.example_id,
                ),
            )
        elif lexical_rerank_weight > 0.0:
            query_tokens = normalized_lexical_tokens(task["question"])
            candidates = [
                replace(
                    candidate,
                    ranking_score=candidate.ranking_score
                    - lexical_rerank_weight
                    * lexical_overlap(query_tokens, candidate),
                )
                for candidate in eligible
            ]
            candidates.sort(key=lambda item: (item.ranking_score, item.example_id))
        else:
            candidates = eligible
        displayed = EVALUATOR.one_per_page(candidates)[:DISPLAY_LIMIT]
        outcome = EVALUATOR.score_task(task, displayed, candidate_pool)
        outcomes.append(outcome)
    return summarize_variant(
        name,
        tasks,
        outcomes,
        {
            "retriever": "dense",
            "distance_cutoff": distance_cutoff,
            "legacy_main_preferences": legacy_preferences,
            "legacy_rank_strength": legacy_rank_strength,
            "target_platform_bias": target_platform_bias,
            "lexical_rerank_weight": lexical_rerank_weight,
            "include_same_page_examples": include_same_page_examples,
            "candidate_budget": CANDIDATE_BUDGET,
            "display_limit": DISPLAY_LIMIT,
        },
    )


def normalized_lexical_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9_]+", text.lower())
    normalized = []
    for word in words:
        if word == "standard":
            continue
        if word == "output" and "standard" in words:
            word = "stdout"
        elif word in {"ipv4", "ipv6"}:
            word = "ip"
        elif word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("es") and len(word) > 5:
            word = word[:-2]
        elif word.endswith("s") and len(word) > 4:
            word = word[:-1]
        if word not in LEXICAL_STOP_WORDS:
            normalized.append(word)
    return set(normalized)


def lexical_overlap(query_tokens: set[str], candidate: Any) -> float:
    candidate_text = " ".join(
        [
            Path(candidate.source_path).stem,
            candidate.command,
            candidate.page_description,
            candidate.example_description,
        ]
    )
    candidate_tokens = normalized_lexical_tokens(candidate_text)
    return len(query_tokens & candidate_tokens) / max(1, len(query_tokens))


def legacy_adjusted_distance(candidate: Any) -> float:
    """Apply main's command/domain distance multipliers to a cosine-ranked row."""
    return legacy_main_distance(candidate) * legacy_rank_multiplier(candidate)


def legacy_rank_multiplier(candidate: Any) -> float:
    command = Path(candidate.source_path).stem.replace(" ", "-")
    description = candidate.page_description
    multiplier = 0.8 if EVALUATOR.is_official_source(description) else 1.0
    if EVALUATOR.is_core_command(command):
        multiplier *= 0.67
    elif EVALUATOR.is_niche_variant(command):
        multiplier *= 1.33
    return multiplier


def partially_adjusted_distance(candidate: Any, strength: float) -> float:
    """Blend main's command preference weights into the raw cosine ranking."""
    raw_distance = max(0.0, candidate.ranking_score)
    multiplier = legacy_rank_multiplier(candidate)
    return raw_distance * (1.0 + strength * (multiplier - 1.0))


def legacy_main_distance(candidate: Any) -> float:
    """sqlite-vec's legacy pages_vec table uses default L2 distance."""
    cosine_distance = max(0.0, candidate.ranking_score)
    return math.sqrt(2.0 * cosine_distance)


def fuse_all_examples(
    keyword_candidates: Sequence[Any],
    dense_candidates: Sequence[Any],
    *,
    keyword_weight: float,
    dense_weight: float,
    weak_match_cutoff: float,
    keyword_budget: int = CANDIDATE_BUDGET,
    dense_budget: int = CANDIDATE_BUDGET,
) -> tuple[list[Any], list[Any]]:
    """Fuse per-example pools, then diversify to one displayed example per page."""
    pools = (
        (list(keyword_candidates)[:keyword_budget], keyword_weight),
        (list(dense_candidates)[:dense_budget], dense_weight),
    )
    by_id: dict[str, Any] = {}
    scores: dict[str, float] = {}
    for candidates, weight in pools:
        for rank, candidate in enumerate(candidates, start=1):
            previous = by_id.get(candidate.example_id)
            if previous is not None and EVALUATOR.candidate_identity(
                previous
            ) != EVALUATOR.candidate_identity(candidate):
                raise ValueError(
                    f"candidate identity mismatch for {candidate.example_id}"
                )
            by_id.setdefault(candidate.example_id, candidate)
            scores[candidate.example_id] = scores.get(candidate.example_id, 0.0) + (
                weight / (RRF_K + rank)
            )

    maximum_score = (keyword_weight + dense_weight) / (RRF_K + 1)
    ranked_ids = sorted(by_id, key=lambda example_id: (-scores[example_id], example_id))
    fused = [
        replace(by_id[example_id], ranking_score=-(scores[example_id] / maximum_score))
        for example_id in ranked_ids
    ]
    accepted = [
        candidate
        for candidate in fused
        if -candidate.ranking_score > weak_match_cutoff
    ]
    displayed = EVALUATOR.one_per_page(accepted)[:DISPLAY_LIMIT]
    return fused, displayed


def score_hybrid(
    name: str,
    tasks: Sequence[dict[str, Any]],
    keyword_pools: dict[str, list[Any]],
    dense_pools: dict[str, list[Any]],
    *,
    dense_distance_cutoff: float | None,
    weak_match_cutoff: float,
    keyword_weight: float = KEYWORD_WEIGHT,
    dense_weight: float = DENSE_WEIGHT,
    delay_page_diversity: bool = False,
) -> dict[str, Any]:
    outcomes = []
    config = EVALUATOR.HybridCandidateConfig(
        candidate_id=name,
        rrf_k=RRF_K,
        keyword_weight=keyword_weight,
        dense_weight=dense_weight,
        keyword_budget=CANDIDATE_BUDGET,
        dense_budget=CANDIDATE_BUDGET,
        weak_match_cutoff=weak_match_cutoff,
    )
    for task in tasks:
        task_id = task["id"]
        dense_candidates = list(dense_pools[task_id])
        if dense_distance_cutoff is not None:
            dense_candidates = [
                candidate
                for candidate in dense_candidates
                if candidate.ranking_score <= dense_distance_cutoff
            ]
        if delay_page_diversity:
            fused, displayed = fuse_all_examples(
                keyword_pools[task_id],
                dense_candidates,
                keyword_weight=keyword_weight,
                dense_weight=dense_weight,
                weak_match_cutoff=weak_match_cutoff,
            )
        else:
            fused = EVALUATOR.fuse_candidates(
                keyword_pools[task_id], dense_candidates, config
            )
            displayed = EVALUATOR.hybrid_results(fused, config)
        outcomes.append(EVALUATOR.score_task(task, displayed, fused))
    return summarize_variant(
        name,
        tasks,
        outcomes,
        {
            "retriever": "hybrid",
            "fusion": "rrf",
            "rrf_k": RRF_K,
            "keyword_weight": keyword_weight,
            "dense_weight": dense_weight,
            "keyword_budget": CANDIDATE_BUDGET,
            "dense_budget": CANDIDATE_BUDGET,
            "dense_distance_cutoff": dense_distance_cutoff,
            "weak_match_cutoff": weak_match_cutoff,
            "page_diversity": "after-fusion" if delay_page_diversity else "before-fusion",
        },
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest = Path(args.manifest)
    dataset_path = Path(args.dataset)
    description_artifact = Path(args.description_artifact)
    parent_artifact = Path(args.description_plus_parent_artifact)
    main_artifact = Path(args.main_compatible_artifact)
    corpus_reference_artifact = Path(args.corpus_reference_artifact)
    corpus_reference_manifest = Path(args.corpus_reference_manifest)
    model_cache = Path(args.model_cache)
    dataset = EVALUATOR.load_json(dataset_path)
    EVALUATOR.validate_dataset(dataset, "dev")
    tasks = [task for task in dataset["tasks"] if task["split"] == "dev"]
    if len(tasks) != len(dataset["tasks"]):
        raise ValueError("controlled ablations accept a dev-only dataset")

    with (
        sqlite3.connect(description_artifact) as description_db,
        sqlite3.connect(parent_artifact) as parent_db,
        sqlite3.connect(main_artifact) as main_db,
    ):
        if example_inventory(description_db) != example_inventory(main_db):
            raise ValueError("representation artifacts do not contain identical examples")
        if example_inventory(parent_db) != example_inventory(main_db):
            raise ValueError("parent representation differs from the pinned examples")
        with closing(sqlite3.connect(corpus_reference_artifact)) as reference_db:
            reference_metadata = EVALUATOR.metadata(reference_db)
            reference_inventory = example_inventory(reference_db)
        if reference_metadata.get("parser_version") != dataset["corpus"].get(
            "parser_version"
        ):
            raise ValueError("reference artifact parser differs from frozen dev labels")
        for field in ("source_revision", "source_digest"):
            if reference_metadata.get(field) != dataset["corpus"].get(field):
                raise ValueError(f"reference artifact {field} differs from frozen dev labels")
        if sha256_file(corpus_reference_manifest) != dataset["corpus"].get(
            "manifest_sha256"
        ):
            raise ValueError("reference manifest digest differs from frozen dev labels")
        candidate_inventory = example_inventory(main_db)
        if reference_inventory != candidate_inventory:
            raise ValueError("candidate rows differ from the parser-v3 reference records")
        inventory_sha256 = hashlib.sha256(
            json.dumps(
                candidate_inventory, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
        dataset_corpus = dataset["corpus"]
        candidate_metadata = EVALUATOR.metadata(main_db)
        for field in ("source_revision", "source_digest"):
            if candidate_metadata.get(field) != dataset_corpus.get(field):
                raise ValueError(
                    f"candidate artifact {field} differs from frozen dev labels"
                )
        candidate_dataset = {
            **dataset,
            "corpus": {
                **dataset_corpus,
                "artifact_kind": candidate_metadata["artifact_kind"],
                "schema_version": candidate_metadata["schema_version"],
                "parser_version": candidate_metadata["parser_version"],
                "manifest_sha256": sha256_file(manifest),
            },
        }
        candidate_corpus_identity = (
            f"{candidate_metadata['source_revision']}:{candidate_metadata['source_digest']}"
        )
        if candidate_dataset["corpus"].get("corpus_id") != candidate_corpus_identity:
            raise ValueError("candidate source identity differs from frozen dev labels")
        description_corpus = EVALUATOR.validate_artifact(
            description_db, candidate_dataset, manifest
        )
        EVALUATOR.validate_artifact(parent_db, candidate_dataset, manifest)
        main_corpus = EVALUATOR.validate_artifact(main_db, candidate_dataset, manifest)
        EVALUATOR.validate_labels(description_db, tasks)
        EVALUATOR.validate_labels(parent_db, tasks)
        EVALUATOR.validate_labels(main_db, tasks)

        keyword_pools = {
            task["id"]: EVALUATOR.fetch_candidates(
                description_db, task["question"], task["platform"], limit=None
            )
            for task in tasks
        }

        dense_description_raw, description_resources = collect_dense(
            args.dense_helper,
            description_artifact,
            model_cache,
            tasks,
            query_mode="raw",
            include_same_page_examples=False,
        )
        dense_parent_raw, parent_resources = collect_dense(
            args.dense_helper,
            parent_artifact,
            model_cache,
            tasks,
            query_mode="raw",
            include_same_page_examples=False,
        )
        dense_main_raw, main_raw_resources = collect_dense(
            args.dense_helper,
            main_artifact,
            model_cache,
            tasks,
            query_mode="raw",
            include_same_page_examples=False,
        )
        dense_main_legacy, main_legacy_resources = collect_dense(
            args.dense_helper,
            main_artifact,
            model_cache,
            tasks,
            query_mode="raw",
            include_same_page_examples=True,
            candidate_budget=LEGACY_MAIN_CANDIDATE_BUDGET,
        )
        dense_main_raw_examples, main_raw_examples_resources = collect_dense(
            args.dense_helper,
            main_artifact,
            model_cache,
            tasks,
            query_mode="raw",
            include_same_page_examples=True,
        )
        dense_main_expanded, main_expanded_resources = collect_dense(
            args.dense_helper,
            main_artifact,
            model_cache,
            tasks,
            query_mode="expanded-dev",
            include_same_page_examples=False,
        )
        dense_main_focused, main_focused_resources = collect_dense(
            args.dense_helper,
            main_artifact,
            model_cache,
            tasks,
            query_mode="focused-v1",
            include_same_page_examples=False,
        )
        dense_main_expanded_examples, main_expanded_examples_resources = collect_dense(
            args.dense_helper,
            main_artifact,
            model_cache,
            tasks,
            query_mode="expanded-dev",
            include_same_page_examples=True,
        )

        results: dict[str, Any] = {}
        results["keyword_early_page_selection"] = summarize_variant(
            "keyword_early_page_selection",
            tasks,
            [
                EVALUATOR.score_task(
                    task,
                    EVALUATOR.one_per_page(keyword_pools[task["id"]])[:DISPLAY_LIMIT],
                    keyword_pools[task["id"]],
                )
                for task in tasks
            ],
            {"retriever": "keyword", "page_diversity": "before-display"},
        )
        results["dense_description_raw"] = score_dense(
            "dense_description_raw",
            tasks,
            dense_description_raw,
            distance_cutoff=None,
        )
        results["dense_description_plus_parent_raw"] = score_dense(
            "dense_description_plus_parent_raw",
            tasks,
            dense_parent_raw,
            distance_cutoff=None,
        )
        for cutoff in (0.45, 0.50, 0.55, 0.60):
            label = f"dense_description_plus_parent_raw_cutoff_{cutoff:.2f}"
            results[label] = score_dense(
                label,
                tasks,
                dense_parent_raw,
                distance_cutoff=cutoff,
            )
        for cutoff in (0.45, 0.50, 0.55, 0.60):
            label = f"dense_description_raw_cutoff_{cutoff:.2f}"
            results[label] = score_dense(
                label,
                tasks,
                dense_description_raw,
                distance_cutoff=cutoff,
            )
        results["dense_main_compatible_raw"] = score_dense(
            "dense_main_compatible_raw",
            tasks,
            dense_main_raw,
            distance_cutoff=None,
        )
        results["dense_main_compatible_raw_same_page_cutoff_0.55"] = score_dense(
            "dense_main_compatible_raw_same_page_cutoff_0.55",
            tasks,
            dense_main_raw_examples,
            distance_cutoff=0.55,
            include_same_page_examples=True,
        )
        for weight in (0.025, 0.05, 0.10, 0.20):
            label = f"dense_main_compatible_raw_same_page_lexical_{weight:.3f}"
            results[label] = score_dense(
                label,
                tasks,
                dense_main_raw_examples,
                distance_cutoff=0.55,
                lexical_rerank_weight=weight,
                include_same_page_examples=True,
            )
        results["dense_main_legacy_rank_policy"] = score_dense(
            "dense_main_legacy_rank_policy",
            tasks,
            dense_main_legacy,
            distance_cutoff=1.10,
            legacy_preferences=True,
        )
        for cutoff in (0.45, 0.50, 0.55, 0.60, 1.0):
            label = f"dense_main_compatible_raw_cutoff_{cutoff:.2f}"
            results[label] = score_dense(
                label,
                tasks,
                dense_main_raw,
                distance_cutoff=cutoff,
            )
        for strength in (0.25, 0.50, 0.75, 1.00):
            label = f"dense_main_compatible_raw_cutoff_0.55_rank_blend_{strength:.2f}"
            results[label] = score_dense(
                label,
                tasks,
                dense_main_raw,
                distance_cutoff=0.55,
                legacy_rank_strength=strength,
            )
        for bias in (0.01, 0.025, 0.05):
            label = f"dense_main_compatible_raw_cutoff_0.55_platform_bias_{bias:.3f}"
            results[label] = score_dense(
                label,
                tasks,
                dense_main_raw,
                distance_cutoff=0.55,
                target_platform_bias=bias,
            )
        results["dense_main_compatible_legacy_preferences_cutoff_0.55"] = score_dense(
            "dense_main_compatible_legacy_preferences_cutoff_0.55",
            tasks,
            dense_main_raw,
            distance_cutoff=0.55,
            legacy_preferences=True,
        )
        results["dense_main_compatible_expanded_dev_cutoff_0.55"] = score_dense(
            "dense_main_compatible_expanded_dev_cutoff_0.55",
            tasks,
            dense_main_expanded,
            distance_cutoff=0.55,
        )
        results["dense_main_compatible_focused_v1_cutoff_0.55"] = score_dense(
            "dense_main_compatible_focused_v1_cutoff_0.55",
            tasks,
            dense_main_focused,
            distance_cutoff=0.55,
        )
        results["hybrid_description_raw_guarded"] = score_hybrid(
            "hybrid_description_raw_guarded",
            tasks,
            keyword_pools,
            dense_description_raw,
            dense_distance_cutoff=0.55,
            weak_match_cutoff=0.50,
        )
        results["hybrid_main_compatible_raw_guarded"] = score_hybrid(
            "hybrid_main_compatible_raw_guarded",
            tasks,
            keyword_pools,
            dense_main_raw,
            dense_distance_cutoff=0.55,
            weak_match_cutoff=0.50,
        )
        results["hybrid_main_compatible_raw_no_weak_cutoff"] = score_hybrid(
            "hybrid_main_compatible_raw_no_weak_cutoff",
            tasks,
            keyword_pools,
            dense_main_raw,
            dense_distance_cutoff=0.55,
            weak_match_cutoff=0.0,
        )
        results["hybrid_main_compatible_raw_no_dense_cutoff"] = score_hybrid(
            "hybrid_main_compatible_raw_no_dense_cutoff",
            tasks,
            keyword_pools,
            dense_main_raw,
            dense_distance_cutoff=None,
            weak_match_cutoff=0.50,
        )
        results["hybrid_main_compatible_raw_equal_weights"] = score_hybrid(
            "hybrid_main_compatible_raw_equal_weights",
            tasks,
            keyword_pools,
            dense_main_raw,
            dense_distance_cutoff=0.55,
            weak_match_cutoff=0.50,
            keyword_weight=1.0,
            dense_weight=1.0,
        )
        results["hybrid_main_compatible_raw_late_page_selection"] = score_hybrid(
            "hybrid_main_compatible_raw_late_page_selection",
            tasks,
            keyword_pools,
            dense_main_raw_examples,
            dense_distance_cutoff=0.55,
            weak_match_cutoff=0.50,
            delay_page_diversity=True,
        )
        results["hybrid_main_compatible_expanded_dev_guarded"] = score_hybrid(
            "hybrid_main_compatible_expanded_dev_guarded",
            tasks,
            keyword_pools,
            dense_main_expanded,
            dense_distance_cutoff=0.55,
            weak_match_cutoff=0.50,
        )

    resources = {
        "description_dense_raw": description_resources,
        "description_plus_parent_dense_raw": parent_resources,
        "main_compatible_dense_raw": main_raw_resources,
        "main_legacy_dense_raw_top7_examples": main_legacy_resources,
        "main_compatible_dense_raw_same_page": main_raw_examples_resources,
        "main_compatible_dense_expanded_dev": main_expanded_resources,
        "main_compatible_dense_expanded_dev_same_page": main_expanded_examples_resources,
        "main_compatible_dense_focused_v1": main_focused_resources,
    }
    return {
        "report_kind": "askman-controlled-retrieval-ablation-dev-v2",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "split": "dev",
        "dataset": {
            "path": str(dataset_path),
            "sha256": sha256_file(dataset_path),
            "task_count": len(tasks),
            "frozen_corpus_identity": dataset["corpus"],
        },
        "manifest": {"path": str(manifest), "sha256": sha256_file(manifest)},
        "corpus": description_corpus,
        "corpus_record_equivalence": {
            "records_identical": True,
            "reference_parser_version": reference_metadata["parser_version"],
            "candidate_parser_version": candidate_metadata["parser_version"],
            "reference_artifact_sha256": sha256_file(corpus_reference_artifact),
            "reference_manifest_sha256": sha256_file(corpus_reference_manifest),
            "example_count": len(reference_inventory),
            "example_inventory_sha256": inventory_sha256,
        },
        "representations": {
            "description_artifact_sha256": sha256_file(description_artifact),
            "description_plus_parent_artifact_sha256": sha256_file(parent_artifact),
            "main_compatible_artifact_sha256": sha256_file(main_artifact),
            "visible_example_count": len(example_inventory(description_db)),
            "identical_visible_examples": True,
            "visible_example_inventory_sha256": hashlib.sha256(
                json.dumps(
                    example_inventory(main_db),
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
            ).hexdigest(),
            "main_compatible_corpus": main_corpus,
        },
        "helper": {
            "path": str(args.dense_helper),
            "sha256": sha256_file(args.dense_helper),
            "evaluator_sha256": sha256_file(EVALUATOR_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
        },
        "resources": resources,
        "holdout_access": {"authorized": False, "recorded": False, "utc": None},
        "results": results,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--manifest", required=True, type=Path)
    result.add_argument("--dataset", required=True, type=Path)
    result.add_argument("--description-artifact", required=True, type=Path)
    result.add_argument("--description-plus-parent-artifact", required=True, type=Path)
    result.add_argument("--main-compatible-artifact", required=True, type=Path)
    result.add_argument("--corpus-reference-artifact", required=True, type=Path)
    result.add_argument(
        "--corpus-reference-manifest",
        type=Path,
        default=ROOT / "tests/fixtures/tldr-evaluation-v2/manifest.json",
    )
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
    except (
        AttributeError,
        KeyError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        TypeError,
        ValueError,
    ) as error:
        print(f"controlled retrieval evaluation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
