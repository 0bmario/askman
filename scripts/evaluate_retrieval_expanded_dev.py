#!/usr/bin/env python3
"""Score the versioned hybrid policy on the expanded development split only.

The frozen evaluator remains unchanged. This runner reuses its source-backed
validation and task scorer, then applies the separately versioned expanded-dev
policy, including the dense-distance guard before RRF fusion.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_VERSION = "expanded-dev-hybrid-v1"
FROZEN_EVALUATOR_PATH = ROOT / "scripts/evaluate_retrieval.py"


def load_frozen_evaluator():
    spec = importlib.util.spec_from_file_location(
        "askman_frozen_evaluator", FROZEN_EVALUATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load frozen evaluator {FROZEN_EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EVALUATOR = load_frozen_evaluator()


@dataclass(frozen=True)
class Policy:
    rrf_k: int
    keyword_weight: float
    dense_weight: float
    keyword_budget: int
    dense_budget: int
    dense_distance_cutoff: float
    weak_match_cutoff: float
    max_displayed_results: int


def require_number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"expanded-dev config {name} must be a number")
    converted = float(value)
    if not math.isfinite(converted) or not minimum <= converted <= maximum:
        raise ValueError(
            f"expanded-dev config {name} must be finite and from {minimum} through {maximum}"
        )
    return converted


def require_integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"expanded-dev config {name} must be an integer from {minimum} through {maximum}"
        )
    if not minimum <= value <= maximum:
        raise ValueError(
            f"expanded-dev config {name} must be an integer from {minimum} through {maximum}"
        )
    return value


def load_config(
    path: Path, dataset: dict[str, Any], dataset_sha256: str
) -> tuple[dict[str, Any], Policy]:
    raw = EVALUATOR.load_json(path)
    if raw.get("schema_version") != 1:
        raise ValueError("unsupported expanded-dev hybrid config schema")
    if raw.get("config_id") != "hybrid-expanded-dev-v1":
        raise ValueError("unexpected expanded-dev hybrid config ID")
    if raw.get("frozen") is not True:
        raise ValueError("expanded-dev hybrid config must be frozen")
    if raw.get("dataset_id") != dataset.get("dataset_id"):
        raise ValueError("expanded-dev hybrid config dataset ID does not match")
    if raw.get("split_id") != dataset.get("split_id"):
        raise ValueError("expanded-dev hybrid config split ID does not match")

    dataset_identity = raw.get("dataset")
    if not isinstance(dataset_identity, dict):
        raise ValueError("expanded-dev hybrid config is missing dataset identity")
    if dataset_identity.get("sha256") != dataset_sha256:
        raise ValueError("expanded-dev hybrid config dataset digest does not match")

    expected_corpus = dataset.get("corpus")
    if raw.get("corpus") != expected_corpus:
        raise ValueError("expanded-dev hybrid config corpus identity does not match")

    evaluator_identity = raw.get("evaluator")
    if not isinstance(evaluator_identity, dict):
        raise ValueError("expanded-dev hybrid config is missing evaluator identity")
    if evaluator_identity.get("version") != EVALUATOR_VERSION:
        raise ValueError("expanded-dev hybrid config evaluator version does not match")
    if evaluator_identity.get("implementation") != str(
        Path(__file__).relative_to(ROOT)
    ):
        raise ValueError("expanded-dev hybrid config evaluator path does not match")
    if evaluator_identity.get("sha256") != EVALUATOR.sha256_file(Path(__file__)):
        raise ValueError("expanded-dev hybrid config evaluator digest does not match")

    scorer_identity = raw.get("scorer")
    if not isinstance(scorer_identity, dict):
        raise ValueError("expanded-dev hybrid config is missing scorer identity")
    if scorer_identity.get("version") != EVALUATOR.SCORER_VERSION:
        raise ValueError("expanded-dev hybrid config scorer version does not match")
    if scorer_identity.get("implementation") != "scripts/evaluate_retrieval.py":
        raise ValueError("expanded-dev hybrid config scorer path does not match")
    if scorer_identity.get("sha256") != EVALUATOR.sha256_file(FROZEN_EVALUATOR_PATH):
        raise ValueError("expanded-dev hybrid config scorer digest does not match")

    if raw.get("dense_recipe") != "description":
        raise ValueError("expanded-dev hybrid config must use the frozen dense recipe")

    raw_policy = raw.get("policy")
    if not isinstance(raw_policy, dict):
        raise ValueError("expanded-dev hybrid config is missing policy")
    fusion = raw_policy.get("fusion")
    budgets = raw_policy.get("candidate_budgets")
    if not isinstance(fusion, dict) or fusion.get("method") != "rrf":
        raise ValueError("expanded-dev policy must use rrf fusion")
    if not isinstance(budgets, dict):
        raise ValueError("expanded-dev policy is missing candidate budgets")
    max_displayed_results = require_integer(
        raw_policy.get("max_displayed_results"),
        "max_displayed_results",
        1,
        EVALUATOR.MAX_DISPLAYED_RESULTS,
    )
    if max_displayed_results != EVALUATOR.MAX_DISPLAYED_RESULTS:
        raise ValueError("expanded-dev policy must retain the three-result display cap")

    policy = Policy(
        rrf_k=require_integer(fusion.get("rrf_k"), "rrf_k", 1, 1000),
        keyword_weight=require_number(
            fusion.get("keyword_weight"), "keyword_weight", 0.01, 4.0
        ),
        dense_weight=require_number(
            fusion.get("dense_weight"), "dense_weight", 0.01, 4.0
        ),
        keyword_budget=require_integer(
            budgets.get("keyword"), "candidate_budgets.keyword", 1, 64
        ),
        dense_budget=require_integer(
            budgets.get("dense"), "candidate_budgets.dense", 1, 64
        ),
        dense_distance_cutoff=require_number(
            raw_policy.get("dense_distance_cutoff"),
            "dense_distance_cutoff",
            0.0,
            1.0,
        ),
        weak_match_cutoff=require_number(
            raw_policy.get("weak_match_cutoff"), "weak_match_cutoff", 0.0, 1.0
        ),
        max_displayed_results=max_displayed_results,
    )
    return raw, policy


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.split != "dev":
        raise ValueError("expanded-dev hybrid evaluation is development-only")

    dataset_path = Path(args.dataset)
    dataset_sha256 = EVALUATOR.sha256_file(dataset_path)
    dataset = EVALUATOR.load_json(dataset_path)
    EVALUATOR.validate_dataset(dataset, "dev")
    config_path = Path(args.config)
    config, policy = load_config(config_path, dataset, dataset_sha256)
    config_sha256 = EVALUATOR.sha256_file(config_path)

    dense_client = None
    task_results: list[dict[str, Any]] = []
    with sqlite3.connect(args.artifact) as connection:
        frozen_artifact = EVALUATOR.validate_artifact(
            connection, dataset, Path(args.manifest) if args.manifest else None
        )
        if connection.execute(
            "SELECT value FROM artifact_metadata WHERE key = 'dense_embedding_text_recipe'"
        ).fetchone() != ("description",):
            raise ValueError("expanded-dev artifact does not use the description recipe")
        EVALUATOR.validate_labels(connection, dataset["tasks"])
        dense_client = EVALUATOR.DenseClient(
            args.dense_helper, args.artifact, args.model_cache
        )
        try:
            for task in dataset["tasks"]:
                keyword_candidates = EVALUATOR.fetch_candidates(
                    connection,
                    task["question"],
                    task["platform"],
                    policy.keyword_budget,
                )
                dense_candidates = dense_client.query(
                    task["question"], task["platform"], policy.dense_budget
                )
                kept_dense_candidates = [
                    candidate
                    for candidate in dense_candidates
                    if candidate.ranking_score <= policy.dense_distance_cutoff
                ]
                fusion_config = EVALUATOR.HybridCandidateConfig(
                    candidate_id=config["config_id"],
                    rrf_k=policy.rrf_k,
                    keyword_weight=policy.keyword_weight,
                    dense_weight=policy.dense_weight,
                    keyword_budget=policy.keyword_budget,
                    dense_budget=policy.dense_budget,
                    weak_match_cutoff=policy.weak_match_cutoff,
                )
                fused_candidates = EVALUATOR.fuse_candidates(
                    keyword_candidates, kept_dense_candidates, fusion_config
                )
                displayed = EVALUATOR.hybrid_results(
                    fused_candidates, fusion_config
                )
                result = EVALUATOR.score_task(task, displayed, fused_candidates)
                result["dense_candidates"] = [
                    {
                        "example_id": candidate.example_id,
                        "distance": round(candidate.ranking_score, 6),
                        "kept": candidate in kept_dense_candidates,
                    }
                    for candidate in dense_candidates
                ]
                result["dense_candidates_kept"] = len(kept_dense_candidates)
                task_results.append(result)
        finally:
            resources = dense_client.resources()
            dense_client.close()

    return {
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": dataset_sha256,
        "dataset_schema_version": dataset["schema_version"],
        "scorer_version": dataset["scorer_version"],
        "scorer_sha256": config["scorer"]["sha256"],
        "evaluator_version": EVALUATOR_VERSION,
        "evaluator_sha256": EVALUATOR.sha256_file(Path(__file__)),
        "config_id": config["config_id"],
        "config_sha256": config_sha256,
        "split_id": dataset["split_id"],
        "split": "dev",
        "retriever": "hybrid",
        "retriever_version": "hybrid-rrf-expanded-dev-v1",
        "corpus": frozen_artifact,
        "policy": config["policy"],
        "resources": resources,
        "summary": EVALUATOR.summarize(dataset["tasks"], task_results),
        "holdout_access": {
            "authorized": False,
            "recorded": False,
            "utc": None,
        },
        "tasks": task_results,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--artifact", required=True, type=Path)
    result.add_argument("--manifest", required=True, type=Path)
    result.add_argument("--dataset", required=True, type=Path)
    result.add_argument("--config", required=True, type=Path)
    result.add_argument("--dense-helper", required=True, type=Path)
    result.add_argument("--model-cache", required=True, type=Path)
    result.add_argument("--split", choices=("dev",), default="dev")
    result.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run(args)
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(encoded, encoding="utf-8")
        else:
            print(encoded, end="")
    except (
        AttributeError,
        KeyError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        TypeError,
        ValueError,
    ) as error:
        print(f"evaluation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
