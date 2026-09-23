#!/usr/bin/env python3
"""Run the non-frozen development behavior-variant baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import evaluate_retrieval as EVALUATOR


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CONFIG_ID = "dev-variant-hybrid-v1"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_project_path(path: str) -> Path:
    return (ROOT / path).resolve()


def load_config(
    path: Path,
    dataset: dict[str, Any],
    dataset_sha256: str,
    artifact_path: Path,
    bundle_manifest_path: Path,
    source_manifest_path: Path,
    dense_helper_path: Path,
    model_cache_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = EVALUATOR.load_json(path)
    if config.get("config_id") != EXPECTED_CONFIG_ID:
        raise ValueError("unexpected dev-variant config ID")
    if config.get("schema_version") != 1:
        raise ValueError("unsupported dev-variant config schema")
    if config.get("freeze_status") != "NON-FROZEN":
        raise ValueError("dev-variant config must be explicitly non-frozen")
    if config.get("candidate_id") != "hybrid":
        raise ValueError("dev-variant config must select the hybrid candidate")
    if config.get("split") != "dev" or dataset.get("split") != "dev":
        raise ValueError("dev-variant evaluation only accepts the dev split")

    dataset_identity = config.get("dataset")
    if not isinstance(dataset_identity, dict):
        raise ValueError("dev-variant config is missing dataset identity")
    if dataset_identity.get("dataset_id") != dataset.get("dataset_id"):
        raise ValueError("dev-variant config dataset ID does not match")
    if dataset_identity.get("sha256") != dataset_sha256:
        raise ValueError("dev-variant config dataset digest does not match")
    if config.get("corpus") != dataset.get("corpus"):
        raise ValueError("dev-variant config corpus identity does not match")

    source_policy_identity = config.get("source_policy_config")
    if not isinstance(source_policy_identity, dict):
        raise ValueError("dev-variant config is missing source policy provenance")
    source_policy_path = resolve_project_path(source_policy_identity["path"])
    if file_sha256(source_policy_path) != source_policy_identity.get("sha256"):
        raise ValueError("source hybrid policy config digest does not match")
    source_policy_config = EVALUATOR.load_json(source_policy_path)
    if config.get("policy") != source_policy_config.get("policy"):
        raise ValueError("dev-variant policy differs from the selected hybrid policy")

    source_manifest_identity = config.get("source_manifest")
    if not isinstance(source_manifest_identity, dict):
        raise ValueError("dev-variant config is missing source manifest provenance")
    if file_sha256(source_manifest_path) != source_manifest_identity.get("sha256"):
        raise ValueError("source manifest digest does not match the config")
    if source_manifest_identity.get("path") != str(
        source_manifest_path.resolve().relative_to(ROOT)
    ):
        raise ValueError("source manifest path does not match the config")

    bundle_identity = config.get("bundle")
    if not isinstance(bundle_identity, dict):
        raise ValueError("dev-variant config is missing bundle identity")
    bundle_manifest_sha256 = file_sha256(bundle_manifest_path)
    if bundle_manifest_sha256 != bundle_identity.get("manifest_sha256"):
        raise ValueError("bundle manifest digest does not match the config")
    bundle_manifest = EVALUATOR.load_json(bundle_manifest_path)
    if bundle_manifest.get("bundle_id") != bundle_identity.get("id"):
        raise ValueError("bundle ID does not match the config")
    artifact_sha256 = file_sha256(artifact_path)
    if artifact_sha256 != bundle_identity.get("artifact_sha256"):
        raise ValueError("bundle artifact digest does not match the config")
    if bundle_manifest.get("dense_index", {}).get("sha256") != artifact_sha256:
        raise ValueError("bundle dense index digest does not match the artifact")
    if bundle_manifest.get("source", {}).get("revision") != dataset["corpus"][
        "source_revision"
    ]:
        raise ValueError("bundle source revision does not match the dataset")
    if bundle_manifest.get("source", {}).get("digest") != dataset["corpus"][
        "source_digest"
    ]:
        raise ValueError("bundle source digest does not match the dataset")

    assets = bundle_manifest.get("embedding_model", {}).get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("bundle manifest is missing embedding model assets")
    bundle_root = bundle_manifest_path.resolve().parent
    if model_cache_path.resolve() != (bundle_root / "model-cache").resolve():
        raise ValueError("model cache path does not match the selected bundle")
    verified_assets: list[dict[str, Any]] = []
    for asset in assets:
        asset_path = bundle_root / asset["path"]
        if asset_path.stat().st_size != asset["size_bytes"]:
            raise ValueError(f"bundle asset size mismatch: {asset['path']}")
        asset_sha256 = file_sha256(asset_path)
        if asset_sha256 != asset["sha256"]:
            raise ValueError(f"bundle asset digest mismatch: {asset['path']}")
        verified_assets.append(
            {"path": asset["path"], "sha256": asset_sha256, "size_bytes": asset["size_bytes"]}
        )

    runtime = config.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("dev-variant config is missing runtime identity")
    if os.environ.get("ASKMAN_DENSE_QUERY_MODE") != runtime.get("dense_query_mode"):
        raise ValueError("dense query mode does not match the config")
    runtime_library = Path(runtime["onnxruntime_library_path"])
    if runtime.get("onnxruntime_version") != "1.20.0":
        raise ValueError("dev-variant baseline requires ONNX Runtime 1.20.0")
    if file_sha256(runtime_library) != runtime.get("onnxruntime_library_sha256"):
        raise ValueError("ONNX Runtime library digest does not match the config")

    code = config.get("code")
    if not isinstance(code, dict):
        raise ValueError("dev-variant config is missing code identity")
    code_paths = {
        "evaluate_retrieval_sha256": ROOT / "scripts/evaluate_retrieval.py",
        "evaluate_retrieval_expanded_dev_sha256": ROOT
        / "scripts/evaluate_retrieval_expanded_dev.py",
        "cargo_lock_sha256": ROOT / "Cargo.lock",
    }
    for key, code_path in code_paths.items():
        if file_sha256(code_path) != code.get(key):
            raise ValueError(f"code digest does not match for {code_path.name}")
    if file_sha256(dense_helper_path) != code.get("dense_helper_sha256"):
        raise ValueError("dense helper digest does not match the config")

    policy = config.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("dev-variant config is missing policy")
    fusion = policy.get("fusion")
    budgets = policy.get("candidate_budgets")
    if not isinstance(fusion, dict) or fusion.get("method") != "rrf":
        raise ValueError("dev-variant config must use reciprocal-rank fusion")
    if not isinstance(budgets, dict):
        raise ValueError("dev-variant config is missing candidate budgets")
    if policy.get("max_displayed_results") != EVALUATOR.MAX_DISPLAYED_RESULTS:
        raise ValueError("dev-variant display limit does not match the scorer")

    config["_sha256"] = file_sha256(path)
    config["_verified_bundle_manifest_sha256"] = bundle_manifest_sha256
    config["_verified_artifact_sha256"] = artifact_sha256
    config["_verified_assets"] = verified_assets
    config["_verified_runtime_library_sha256"] = runtime["onnxruntime_library_sha256"]
    config["_verified_code"] = {
        key: file_sha256(code_path) for key, code_path in code_paths.items()
    }
    config["_verified_code"]["dense_helper_sha256"] = file_sha256(dense_helper_path)
    return config, bundle_manifest


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset_path = Path(args.dataset).resolve()
    dataset_sha256 = file_sha256(dataset_path)
    dataset = EVALUATOR.load_json(dataset_path)
    EVALUATOR.validate_dataset(dataset, "dev")

    artifact_path = Path(args.artifact).resolve()
    bundle_manifest_path = Path(args.bundle_manifest).resolve()
    source_manifest_path = Path(args.manifest).resolve()
    dense_helper_path = Path(args.dense_helper).resolve()
    model_cache_path = Path(args.model_cache).resolve()
    config, bundle_manifest = load_config(
        Path(args.config).resolve(),
        dataset,
        dataset_sha256,
        artifact_path,
        bundle_manifest_path,
        source_manifest_path,
        dense_helper_path,
        model_cache_path,
    )

    policy = config["policy"]
    fusion = policy["fusion"]
    budgets = policy["candidate_budgets"]
    fusion_config = EVALUATOR.HybridCandidateConfig(
        candidate_id=config["candidate_id"],
        rrf_k=fusion["rrf_k"],
        keyword_weight=fusion["keyword_weight"],
        dense_weight=fusion["dense_weight"],
        keyword_budget=budgets["keyword"],
        dense_budget=budgets["dense"],
        weak_match_cutoff=policy["weak_match_cutoff"],
    )

    task_results: list[dict[str, Any]] = []
    dense_client = None
    with sqlite3.connect(artifact_path) as connection:
        corpus_identity = EVALUATOR.validate_artifact(
            connection, dataset, source_manifest_path
        )
        if connection.execute(
            "SELECT value FROM artifact_metadata WHERE key = 'dense_embedding_text_recipe'"
        ).fetchone() != ("description",):
            raise ValueError("artifact does not use the configured description recipe")
        EVALUATOR.validate_labels(connection, dataset["tasks"])
        dense_client = EVALUATOR.DenseClient(
            dense_helper_path, artifact_path, model_cache_path
        )
        try:
            for task in dataset["tasks"]:
                keyword_candidates = EVALUATOR.fetch_candidates(
                    connection,
                    task["question"],
                    task["platform"],
                    fusion_config.keyword_budget,
                )
                dense_candidates = dense_client.query(
                    task["question"],
                    task["platform"],
                    fusion_config.dense_budget,
                )
                kept_dense_candidates = [
                    candidate
                    for candidate in dense_candidates
                    if candidate.ranking_score <= policy["dense_distance_cutoff"]
                ]
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

    evaluator_path = ROOT / "scripts/evaluate_retrieval.py"
    expanded_evaluator_path = ROOT / "scripts/evaluate_retrieval_expanded_dev.py"
    harness_path = Path(__file__).resolve()
    runtime = config["runtime"]
    return {
        "evidence_status": "NON-FROZEN DEV-ONLY; NOT RELEASE EVIDENCE",
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": dataset_sha256,
        "dataset_schema_version": dataset["schema_version"],
        "split": "dev",
        "scorer_version": dataset["scorer_version"],
        "candidate_id": config["candidate_id"],
        "retriever": "hybrid",
        "retriever_version": "hybrid-rrf-expanded-dev-v1",
        "config_id": config["config_id"],
        "config_sha256": config["_sha256"],
        "source_policy_config": config["source_policy_config"],
        "policy": policy,
        "corpus": corpus_identity,
        "bundle": {
            "id": bundle_manifest["bundle_id"],
            "manifest_sha256": config["_verified_bundle_manifest_sha256"],
            "artifact_sha256": config["_verified_artifact_sha256"],
            "model_assets": config["_verified_assets"],
        },
        "runtime": {
            "dense_query_mode": runtime["dense_query_mode"],
            "onnxruntime_version": runtime["onnxruntime_version"],
            "onnxruntime_library_sha256": config[
                "_verified_runtime_library_sha256"
            ],
        },
        "code": {
            "dev_harness_sha256": file_sha256(harness_path),
            "evaluate_retrieval_sha256": config["_verified_code"][
                "evaluate_retrieval_sha256"
            ],
            "evaluate_retrieval_expanded_dev_sha256": config["_verified_code"][
                "evaluate_retrieval_expanded_dev_sha256"
            ],
            "cargo_lock_sha256": config["_verified_code"]["cargo_lock_sha256"],
            "dense_helper_sha256": config["_verified_code"]["dense_helper_sha256"],
        },
        "resources": resources,
        "summary": EVALUATOR.summarize(dataset["tasks"], task_results),
        "tasks": task_results,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--artifact", required=True, type=Path)
    result.add_argument("--bundle-manifest", required=True, type=Path)
    result.add_argument("--manifest", required=True, type=Path)
    result.add_argument("--dataset", required=True, type=Path)
    result.add_argument("--config", required=True, type=Path)
    result.add_argument("--dense-helper", required=True, type=Path)
    result.add_argument("--model-cache", required=True, type=Path)
    result.add_argument("--output", required=True, type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run(args)
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        args.output.write_text(encoded, encoding="utf-8")
    except (
        AttributeError,
        KeyError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        TypeError,
        ValueError,
    ) as error:
        print(f"dev-variant evaluation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
