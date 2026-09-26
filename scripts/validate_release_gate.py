#!/usr/bin/env python3
"""Validate the checked-in A/B report required before release publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE_MANIFEST = ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json"
FROZEN_DEV_DATASET = ROOT / "tests/fixtures/evaluation/frozen-dev-v2-expanded.json"
FRESH_HOLDOUT_MANIFEST = ROOT / "tests/fixtures/evaluation/fresh-holdout-v1.manifest.json"
FRESH_HOLDOUT_FREEZE_ID = "fresh-holdout-v1-freeze-2026-09-26"
FRESH_HOLDOUT_MANIFEST_SHA256 = (
    "7463ccb782cf971b4893f369c899f408212306020c68e471b72c146b2da68f1a"
)
FRESH_HOLDOUT_DATASET_SHA256 = (
    "7fe11e153b64941c91233b756543487ebdd34e17bcca7b935a55f8f16a6fb2a0"
)
ALLOWED_NETWORK_POLICIES = {
    "Linux unshare --net",
    "macOS sandbox-exec deny network*",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
# Evaluation-corpus baseline built by the pinned main importer.
PINNED_MAIN_DATABASE_SHA256 = (
    "ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db"
)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
BOOTSTRAP_SEED = 33_031
QUALITY_METRICS = (
    "success_at_1",
    "success_at_3",
    "coverage",
    "incorrect_answered_tasks",
    "false_answers_on_unanswerable",
)
REQUIRED_PLATFORMS = {"common", "linux", "osx", "windows"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_nonempty_string(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"release-gate field is missing or empty: {label}")


def require_digest(value: object, label: str) -> None:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"release-gate field is not a SHA-256 digest: {label}")


def require_number(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"release-gate field is not a finite number: {label}")


def validate_metric(value: object, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"release-gate metric is missing: {label}")
    count = value.get("count")
    denominator = value.get("denominator")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or isinstance(denominator, bool)
        or not isinstance(denominator, int)
        or count < 0
        or denominator < 0
        or count > denominator
    ):
        raise ValueError(f"release-gate metric is invalid: {label}")


def validate_implementation_summaries(value: object, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"release-gate quality summary is missing: {label}")
    for implementation in ("main", "candidate"):
        summary = value.get(implementation)
        if not isinstance(summary, dict):
            raise ValueError(f"release-gate quality summary is missing: {label}.{implementation}")
        for metric in QUALITY_METRICS:
            validate_metric(summary.get(metric), f"{label}.{implementation}.{metric}")
        for count_name in ("tasks", "answerable_tasks", "unanswerable_tasks"):
            count = summary.get(count_name)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(f"release-gate count is invalid: {label}.{implementation}.{count_name}")
        if summary["tasks"] <= 0 or summary["tasks"] != summary["answerable_tasks"] + summary["unanswerable_tasks"]:
            raise ValueError(f"release-gate task counts are inconsistent: {label}.{implementation}")
        if summary["success_at_1"]["denominator"] != summary["answerable_tasks"]:
            raise ValueError(f"release-gate Success@1 denominator is inconsistent: {label}.{implementation}")
        if summary["success_at_3"]["denominator"] != summary["answerable_tasks"]:
            raise ValueError(f"release-gate Success@3 denominator is inconsistent: {label}.{implementation}")
        if summary["coverage"]["denominator"] != summary["tasks"]:
            raise ValueError(f"release-gate coverage denominator is inconsistent: {label}.{implementation}")
        if summary["false_answers_on_unanswerable"]["denominator"] != summary["unanswerable_tasks"]:
            raise ValueError(f"release-gate false-answer denominator is inconsistent: {label}.{implementation}")
        answered_answerable = (
            summary["coverage"]["count"]
            - summary["false_answers_on_unanswerable"]["count"]
        )
        incorrect_answers = summary["incorrect_answered_tasks"]
        if (
            answered_answerable < 0
            or answered_answerable > summary["answerable_tasks"]
            or incorrect_answers["denominator"] != answered_answerable
        ):
            raise ValueError(f"release-gate incorrect-answer denominator is inconsistent: {label}.{implementation}")
        if summary["success_at_1"]["count"] > summary["success_at_3"]["count"]:
            raise ValueError(f"release-gate Success@1 exceeds Success@3: {label}.{implementation}")
        expected_incorrect_answers = answered_answerable - summary["success_at_3"]["count"]
        if expected_incorrect_answers < 0 or incorrect_answers["count"] != expected_incorrect_answers:
            raise ValueError(f"release-gate incorrect-answer count is inconsistent: {label}.{implementation}")

    main_summary = value["main"]
    candidate_summary = value["candidate"]
    assert isinstance(main_summary, dict) and isinstance(candidate_summary, dict)
    for count_name in ("tasks", "answerable_tasks", "unanswerable_tasks"):
        if main_summary[count_name] != candidate_summary[count_name]:
            raise ValueError(f"release-gate implementations use different task counts: {label}")


def validate_quality_summary(value: object, label: str) -> None:
    validate_implementation_summaries(value, label)
    assert isinstance(value, dict)

    platforms = value.get("platform")
    if not isinstance(platforms, dict) or not REQUIRED_PLATFORMS.issubset(platforms):
        raise ValueError(f"release-gate platform breakdown is incomplete: {label}")
    for platform_name, platform_summary in platforms.items():
        validate_implementation_summaries(platform_summary, f"{label}.platform.{platform_name}")

    families = value.get("family")
    if not isinstance(families, dict) or not families:
        raise ValueError(f"release-gate family breakdown is missing: {label}")
    for family_name, family_summary in families.items():
        if not isinstance(family_summary, dict):
            raise ValueError(f"release-gate family breakdown is invalid: {label}.{family_name}")
        validate_implementation_summaries(family_summary, f"{label}.family.{family_name}")
        require_number(family_summary.get("success_at_1_gain"), f"{label}.family.{family_name}.success_at_1_gain")

    failures = value.get("failures")
    if (
        not isinstance(failures, dict)
        or not isinstance(failures.get("main"), list)
        or not isinstance(failures.get("candidate"), list)
    ):
        raise ValueError(f"release-gate failure examples are missing: {label}")


def validate_latency(value: object, label: str, *, require_memory: bool) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"release-gate performance section is missing: {label}")
    for field in ("p50_ms", "p95_ms"):
        require_number(value.get(field), f"{label}.{field}")
    if value["p50_ms"] < 0 or value["p95_ms"] < value["p50_ms"]:
        raise ValueError(f"release-gate latency values are invalid: {label}")
    sample_count = value.get("sample_count")
    memory_sample_count = value.get("memory_sample_count")
    peak_memory = value.get("peak_memory_bytes")
    if (
        isinstance(sample_count, bool)
        or not isinstance(sample_count, int)
        or sample_count <= 0
        or isinstance(memory_sample_count, bool)
        or not isinstance(memory_sample_count, int)
        or memory_sample_count < 0
    ):
        raise ValueError(f"release-gate performance section is invalid: {label}")
    if peak_memory is None:
        if require_memory or memory_sample_count != 0:
            raise ValueError(f"release-gate performance memory section is invalid: {label}")
    elif (
        isinstance(peak_memory, bool)
        or not isinstance(peak_memory, int)
        or peak_memory < 0
        or memory_sample_count <= 0
    ):
        raise ValueError(f"release-gate performance memory section is invalid: {label}")


def metric_rate(metric: dict[str, int]) -> float:
    return metric["count"] / metric["denominator"] if metric["denominator"] else 0.0


def require_no_regression(summary: dict[str, object], label: str) -> None:
    main = summary["main"]
    candidate = summary["candidate"]
    assert isinstance(main, dict) and isinstance(candidate, dict)
    if metric_rate(candidate["success_at_3"]) < metric_rate(main["success_at_3"]):
        raise ValueError(f"release-gate Success@3 regressed: {label}")
    for metric_name in ("incorrect_answered_tasks", "false_answers_on_unanswerable"):
        if metric_rate(candidate[metric_name]) > metric_rate(main[metric_name]):
            raise ValueError(f"release-gate {metric_name} regressed: {label}")


def require_no_platform_success_at_1_regression(
    summary: dict[str, object], label: str
) -> None:
    platforms = summary.get("platform")
    assert isinstance(platforms, dict)
    for platform_name, platform_summary in platforms.items():
        assert isinstance(platform_summary, dict)
        main = platform_summary["main"]
        candidate = platform_summary["candidate"]
        assert isinstance(main, dict) and isinstance(candidate, dict)
        if metric_rate(candidate["success_at_1"]) < metric_rate(main["success_at_1"]):
            raise ValueError(
                f"release-gate Success@1 regressed: {label}.platform.{platform_name}"
            )


def validate_report_evidence(report: dict[str, object]) -> None:
    schema_version = report.get("schema_version")
    if schema_version not in {3, 4}:
        raise ValueError("release-gate report schema version is unsupported")
    if report.get("evidence_id") != "askman-main-vs-retrieval-v2-v1":
        raise ValueError("release-gate evidence id is unsupported")
    if report.get("status") != "complete":
        raise ValueError("release-gate report is not complete")

    protocol = report.get("protocol")
    if not isinstance(protocol, dict):
        raise ValueError("release-gate protocol metadata is missing")
    for field in (
        "development_and_holdout",
        "no_holdout_tuning",
        "setup_download_separate",
        "holdout_access_authorized",
    ):
        if protocol.get(field) is not True:
            raise ValueError(f"release-gate protocol requirement is missing: {field}")
    for field in ("main_ref", "candidate_ref", "timing_policy"):
        require_nonempty_string(protocol.get(field), f"protocol.{field}")

    inputs = report.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("release-gate report has no inputs")
    for field in (
        "freeze_manifest_sha256",
        "main_data_dir_tree_sha256",
        "dev_dataset_sha256",
        "holdout_dataset_sha256",
        "scorer_sha256",
    ):
        require_digest(inputs.get(field), f"inputs.{field}")
    if inputs.get("holdout_dataset_sha256") != FRESH_HOLDOUT_DATASET_SHA256:
        raise ValueError("release-gate holdout is not the pinned fresh independent dataset")
    if (
        inputs.get("independent_holdout_freeze_manifest_sha256")
        != FRESH_HOLDOUT_MANIFEST_SHA256
    ):
        raise ValueError("release-gate independent holdout manifest digest is not pinned")
    if inputs.get("independent_holdout_freeze_id") != FRESH_HOLDOUT_FREEZE_ID:
        raise ValueError("release-gate independent holdout freeze ID is not pinned")
    if protocol.get("holdout_freeze_id") != FRESH_HOLDOUT_FREEZE_ID:
        raise ValueError("release-gate protocol does not identify the fresh holdout")
    if schema_version == 4:
        require_digest(inputs.get("gate_runner_sha256"), "inputs.gate_runner_sha256")
        if inputs["gate_runner_sha256"] != sha256_file(ROOT / "scripts/run_release_gate.py"):
            raise ValueError("release-gate runner digest does not match the report")
    compatibility = inputs.get("input_compatibility")
    if not isinstance(compatibility, dict):
        raise ValueError("release-gate input compatibility evidence is missing")
    require_digest(
        compatibility.get("candidate_source_digest"),
        "inputs.input_compatibility.candidate_source_digest",
    )
    require_nonempty_string(
        compatibility.get("candidate_parser_version"),
        "inputs.input_compatibility.candidate_parser_version",
    )
    require_nonempty_string(
        compatibility.get("candidate_source_revision"),
        "inputs.input_compatibility.candidate_source_revision",
    )
    main_database_sha256 = compatibility.get("main_database_sha256")
    require_digest(
        main_database_sha256,
        "inputs.input_compatibility.main_database_sha256",
    )
    if (
        compatibility.get("main_database_matches_pinned_baseline") is not True
        or main_database_sha256 != PINNED_MAIN_DATABASE_SHA256
    ):
        raise ValueError("release-gate main database does not match the pinned evaluation baseline")
    for field in ("visible_corpus_example_count", "model_asset_count"):
        value = compatibility.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"release-gate input compatibility count is invalid: {field}")
    require_digest(
        compatibility.get("visible_corpus_examples_sha256"),
        "inputs.input_compatibility.visible_corpus_examples_sha256",
    )
    if compatibility.get("model_assets_match") is not True:
        raise ValueError("release-gate model assets do not match")
    benchmark_corpora = inputs.get("benchmark_corpus_compatibility")
    if not isinstance(benchmark_corpora, dict):
        raise ValueError("release-gate benchmark corpus compatibility evidence is missing")
    expected_splits = ("dev", "holdout") if protocol["development_and_holdout"] else ("dev",)
    for split_name in expected_splits:
        benchmark_corpus = benchmark_corpora.get(split_name)
        if not isinstance(benchmark_corpus, dict):
            raise ValueError(
                f"release-gate benchmark corpus evidence is missing: {split_name}"
            )
        if benchmark_corpus.get("matches_candidate_bundle") is not True:
            raise ValueError(
                f"release-gate benchmark corpus does not match candidate bundle: {split_name}"
            )
        for field in ("parser_version", "source_revision"):
            require_nonempty_string(
                benchmark_corpus.get(field),
                f"inputs.benchmark_corpus_compatibility.{split_name}.{field}",
            )
        require_digest(
            benchmark_corpus.get("source_digest"),
            f"inputs.benchmark_corpus_compatibility.{split_name}.source_digest",
        )
        candidate_corpus_identity = {
            "parser_version": compatibility["candidate_parser_version"],
            "source_revision": compatibility["candidate_source_revision"],
            "source_digest": compatibility["candidate_source_digest"],
        }
        if any(
            benchmark_corpus.get(field) != candidate_corpus_identity[field]
            for field in ("source_revision", "source_digest")
        ):
            raise ValueError(
                f"release-gate benchmark corpus source differs from candidate bundle: {split_name}"
            )

        if benchmark_corpus["parser_version"] != compatibility["candidate_parser_version"]:
            equivalence = benchmark_corpus.get("record_equivalence")
            if not isinstance(equivalence, dict):
                raise ValueError(
                    f"release-gate parser versions differ without record equivalence: {split_name}"
                )
            if (
                equivalence.get("records_identical") is not True
                or equivalence.get("reference_parser_version")
                != benchmark_corpus["parser_version"]
                or equivalence.get("candidate_parser_version")
                != compatibility["candidate_parser_version"]
                or equivalence.get("source_revision")
                != compatibility["candidate_source_revision"]
                or equivalence.get("source_digest")
                != compatibility["candidate_source_digest"]
            ):
                raise ValueError(
                    f"release-gate parser-version record equivalence is invalid: {split_name}"
                )
            reference_count = equivalence.get("reference_example_count")
            candidate_count = equivalence.get("candidate_example_count")
            if (
                isinstance(reference_count, bool)
                or not isinstance(reference_count, int)
                or reference_count <= 0
                or candidate_count != reference_count
            ):
                raise ValueError(
                    f"release-gate parser-version record counts differ: {split_name}"
                )
            reference_inventory = equivalence.get("reference_inventory_sha256")
            candidate_inventory = equivalence.get("candidate_inventory_sha256")
            require_digest(
                reference_inventory,
                f"inputs.benchmark_corpus_compatibility.{split_name}.record_equivalence.reference_inventory_sha256",
            )
            require_digest(
                candidate_inventory,
                f"inputs.benchmark_corpus_compatibility.{split_name}.record_equivalence.candidate_inventory_sha256",
            )
            if reference_inventory != candidate_inventory:
                raise ValueError(
                    f"release-gate parser-version record inventories differ: {split_name}"
                )
    if "holdout" in benchmark_corpora:
        dev_corpus = benchmark_corpora["dev"]
        holdout_corpus = benchmark_corpora["holdout"]
        if any(
            holdout_corpus.get(field) != dev_corpus.get(field)
            for field in ("source_revision", "source_digest")
        ):
            raise ValueError("release-gate development and holdout source identities differ")
    for field in ("benchmark_id", "freeze_id"):
        require_nonempty_string(inputs.get(field), f"inputs.{field}")
    bundle = inputs.get("bundle")
    if not isinstance(bundle, dict):
        raise ValueError("release-gate bundle metadata is missing")
    require_nonempty_string(bundle.get("bundle_id"), "inputs.bundle.bundle_id")
    for field in ("manifest_sha256", "bundle_tree_sha256", "staged_tree_sha256"):
        require_digest(bundle.get(field), f"inputs.bundle.{field}")
    for field in ("main_data_file_sha256", "bundle_file_sha256"):
        digests = inputs.get(field)
        if not isinstance(digests, dict) or not digests:
            raise ValueError(f"release-gate per-file digests are missing: inputs.{field}")
        for path, digest in digests.items():
            require_nonempty_string(path, f"inputs.{field} path")
            require_digest(digest, f"inputs.{field}.{path}")
    if inputs["main_data_file_sha256"].get("commands.db") != main_database_sha256:
        raise ValueError("release-gate main database digest does not match input file digest")
    model_asset_digests = compatibility.get("model_asset_digests")
    if (
        not isinstance(model_asset_digests, dict)
        or len(model_asset_digests) != compatibility["model_asset_count"]
    ):
        raise ValueError("release-gate model asset digest evidence is incomplete")
    for relative_path, expected_digest in model_asset_digests.items():
        require_nonempty_string(relative_path, "inputs.input_compatibility.model asset path")
        path_parts = relative_path.split("/")
        if (
            "\\" in relative_path
            or relative_path.startswith("/")
            or any(part in {"", ".", ".."} for part in path_parts)
        ):
            raise ValueError("release-gate model asset path is invalid")
        require_digest(
            expected_digest,
            f"inputs.input_compatibility.model_asset_digests.{relative_path}",
        )
        bundle_asset_digest = inputs["bundle_file_sha256"].get(
            f"model-cache/{relative_path}"
        )
        if bundle_asset_digest != expected_digest:
            raise ValueError(
                f"release-gate model asset digest does not match recorded file inputs: {relative_path}"
            )

    builds = report.get("builds")
    if not isinstance(builds, dict):
        raise ValueError("release-gate build metadata is missing")
    for label in ("main", "candidate"):
        build = builds.get(label)
        if not isinstance(build, dict):
            raise ValueError(f"release-gate build metadata is missing: {label}")
        require_nonempty_string(build.get("ref"), f"builds.{label}.ref")
        commit = build.get("commit")
        if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
            raise ValueError(f"release-gate build commit is invalid: {label}")
        for field in ("cargo_lock_sha256", "binary_sha256"):
            require_digest(build.get(field), f"builds.{label}.{field}")
        if not isinstance(build.get("binary_bytes"), int) or build["binary_bytes"] <= 0:
            raise ValueError(f"release-gate binary size is invalid: {label}")
        command = build.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
            raise ValueError(f"release-gate build command is invalid: {label}")

    quality = report.get("quality")
    if not isinstance(quality, dict):
        raise ValueError("release-gate quality evidence is missing")
    for split in ("dev", "holdout", "combined"):
        validate_quality_summary(quality.get(split), f"quality.{split}")

    combined = quality["combined"]
    main_summary = combined["main"]
    candidate_summary = combined["candidate"]
    family_gains = {
        family: value["success_at_1_gain"] for family, value in combined["family"].items()
    }
    for family, gain in family_gains.items():
        main_metric = combined["family"][family]["main"]["success_at_1"]
        candidate_metric = combined["family"][family]["candidate"]["success_at_1"]
        expected_gain = (
            candidate_metric["count"] / candidate_metric["denominator"]
            if candidate_metric["denominator"]
            else 0.0
        ) - (
            main_metric["count"] / main_metric["denominator"]
            if main_metric["denominator"]
            else 0.0
        )
        if not math.isclose(gain, expected_gain, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(f"release-gate family gain is inconsistent: {family}")

    bootstrap = report.get("bootstrap")
    if not isinstance(bootstrap, dict) or bootstrap.get("resamples") != 10_000:
        raise ValueError("release-gate bootstrap evidence is incomplete")
    if not isinstance(bootstrap.get("seed"), int) or bootstrap["seed"] < 0:
        raise ValueError("release-gate bootstrap seed is invalid")
    if not isinstance(bootstrap.get("paired_task_count"), int) or bootstrap["paired_task_count"] <= 0:
        raise ValueError("release-gate bootstrap task count is invalid")
    require_number(bootstrap.get("observed_success_at_1_gain"), "bootstrap.observed_success_at_1_gain")
    require_number(
        bootstrap.get("one_sided_95_lower_bound"),
        "bootstrap.one_sided_95_lower_bound",
    )
    one_sided_lower_bound = bootstrap["one_sided_95_lower_bound"]
    if one_sided_lower_bound <= 0:
        raise ValueError("release-gate one-sided 95% bootstrap lower bound is not above zero")
    interval = bootstrap.get("interval_95")
    if not isinstance(interval, dict):
        raise ValueError("release-gate bootstrap interval is missing")
    require_number(interval.get("lower"), "bootstrap.interval_95.lower")
    require_number(interval.get("upper"), "bootstrap.interval_95.upper")
    if interval["lower"] > interval["upper"]:
        raise ValueError("release-gate bootstrap interval is invalid")
    if not interval["lower"] <= one_sided_lower_bound <= interval["upper"]:
        raise ValueError("release-gate one-sided bootstrap bound is inconsistent with the interval")
    interval_contains_zero = interval["lower"] <= 0 <= interval["upper"]
    if bootstrap.get("interval_contains_zero") is not interval_contains_zero:
        raise ValueError("release-gate bootstrap zero-crossing flag is inconsistent")
    if bootstrap["paired_task_count"] != main_summary["answerable_tasks"]:
        raise ValueError("release-gate bootstrap task count does not match quality evidence")

    holdout_quality = quality["holdout"]
    holdout_main = holdout_quality["main"]
    holdout_candidate = holdout_quality["candidate"]
    assert isinstance(holdout_main, dict) and isinstance(holdout_candidate, dict)
    independent_bootstrap = report.get("independent_holdout_bootstrap")
    if not isinstance(independent_bootstrap, dict):
        raise ValueError("release-gate independent holdout bootstrap is missing")
    if independent_bootstrap.get("resamples") != 10_000:
        raise ValueError("release-gate independent holdout bootstrap is incomplete")
    if independent_bootstrap.get("seed") != BOOTSTRAP_SEED:
        raise ValueError("release-gate independent holdout bootstrap seed is invalid")
    if independent_bootstrap.get("paired_task_count") != holdout_main["answerable_tasks"]:
        raise ValueError("release-gate independent holdout bootstrap task count is invalid")
    require_number(
        independent_bootstrap.get("observed_success_at_1_gain"),
        "independent_holdout_bootstrap.observed_success_at_1_gain",
    )
    require_number(
        independent_bootstrap.get("one_sided_95_lower_bound"),
        "independent_holdout_bootstrap.one_sided_95_lower_bound",
    )
    expected_holdout_gain = metric_rate(holdout_candidate["success_at_1"]) - metric_rate(
        holdout_main["success_at_1"]
    )
    if not math.isclose(
        independent_bootstrap["observed_success_at_1_gain"],
        expected_holdout_gain,
        rel_tol=1e-9,
        abs_tol=1e-12,
    ):
        raise ValueError("release-gate independent holdout bootstrap gain is inconsistent")
    if independent_bootstrap["one_sided_95_lower_bound"] <= 0:
        raise ValueError("release-gate independent holdout bootstrap lower bound is not positive")
    if expected_holdout_gain < 0.05:
        raise ValueError("release-gate independent holdout Success@1 gain is below five points")
    require_no_regression(holdout_quality, "holdout")
    for platform_name, platform_summary in holdout_quality["platform"].items():
        require_no_regression(platform_summary, f"holdout.platform.{platform_name}")
    require_no_platform_success_at_1_regression(holdout_quality, "holdout")

    independent_gate = report.get("independent_holdout_gate")
    if (
        not isinstance(independent_gate, dict)
        or independent_gate.get("passed") is not True
        or independent_gate.get("decision") != "better_askman"
        or independent_gate.get("reasons") != []
    ):
        raise ValueError("release-gate independent holdout conditions did not pass")
    require_number(
        independent_gate.get("success_at_1_gain"),
        "independent_holdout_gate.success_at_1_gain",
    )
    if not math.isclose(
        independent_gate.get("success_at_1_gain", math.nan),
        expected_holdout_gain,
        rel_tol=1e-9,
        abs_tol=1e-12,
    ):
        raise ValueError("release-gate independent holdout gain is inconsistent")

    performance = report.get("performance")
    if not isinstance(performance, dict):
        raise ValueError("release-gate performance evidence is missing")
    for implementation in ("main", "candidate"):
        measurements = performance.get(implementation)
        if not isinstance(measurements, dict):
            raise ValueError(f"release-gate performance evidence is missing: {implementation}")
        for split in ("dev", "holdout"):
            split_measurements = measurements.get(split)
            if not isinstance(split_measurements, dict):
                raise ValueError(f"release-gate performance evidence is missing: performance.{implementation}.{split}")
            validate_latency(
                split_measurements.get("fresh_process"),
                f"performance.{implementation}.{split}.fresh_process",
                require_memory=True,
            )
        validate_latency(
            measurements.get("warmed_query"),
            f"performance.{implementation}.warmed_query",
            require_memory=True,
        )

    execution = report.get("execution")
    if (
        not isinstance(execution, dict)
        or not isinstance(execution.get("main"), list)
        or not isinstance(execution.get("candidate"), list)
        or execution["main"]
        or execution["candidate"]
    ):
        raise ValueError("release-gate report contains incomplete or failed CLI execution records")

    gate = report.get("gate")
    if not isinstance(gate, dict) or gate.get("passed") is not True or gate.get("decision") != "better_askman":
        raise ValueError("release-gate does not contain a passing decision")
    if gate.get("reasons") != [] or gate.get("family_regressions") != []:
        raise ValueError("release-gate decision contains failure reasons")
    if not isinstance(gate.get("positive_family_count"), int) or gate["positive_family_count"] < 2:
        raise ValueError("release-gate has fewer than two improving families")
    require_number(gate.get("overall_success_at_1_gain"), "gate.overall_success_at_1_gain")
    if gate["overall_success_at_1_gain"] < 0.05:
        raise ValueError("release-gate Success@1 gain is below the release threshold")
    expected_overall_gain = (
        candidate_summary["success_at_1"]["count"] / candidate_summary["success_at_1"]["denominator"]
        if candidate_summary["success_at_1"]["denominator"]
        else 0.0
    ) - (
        main_summary["success_at_1"]["count"] / main_summary["success_at_1"]["denominator"]
        if main_summary["success_at_1"]["denominator"]
        else 0.0
    )
    if not math.isclose(gate["overall_success_at_1_gain"], expected_overall_gain, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError("release-gate overall Success@1 gain is inconsistent")
    if not math.isclose(
        bootstrap["observed_success_at_1_gain"], expected_overall_gain, rel_tol=1e-9, abs_tol=1e-12
    ):
        raise ValueError("release-gate bootstrap gain is inconsistent")
    require_no_regression(combined, "combined")
    for platform_name, platform_summary in combined["platform"].items():
        require_no_regression(platform_summary, f"platform.{platform_name}")
    positive_families = sum(gain > 0 for gain in family_gains.values())
    if gate["positive_family_count"] != positive_families:
        raise ValueError("release-gate positive family count is inconsistent")
    regressions = sorted(family for family, gain in family_gains.items() if gain < 0)
    if sorted(gate["family_regressions"]) != regressions:
        raise ValueError("release-gate family regression list is inconsistent")

    for split in ("dev", "holdout"):
        main_fresh = performance["main"][split]["fresh_process"]
        candidate_fresh = performance["candidate"][split]["fresh_process"]
        if candidate_fresh["p95_ms"] > main_fresh["p95_ms"] * 1.2:
            raise ValueError(
                f"release-gate {split} fresh-process latency exceeds the regression limit"
            )
        if candidate_fresh["peak_memory_bytes"] > main_fresh["peak_memory_bytes"] * 1.2:
            raise ValueError(
                f"release-gate {split} fresh-process memory exceeds the regression limit"
            )
    main_warm = performance["main"]["warmed_query"]
    candidate_warm = performance["candidate"]["warmed_query"]
    if candidate_warm["p95_ms"] > main_warm["p95_ms"] * 1.2:
        raise ValueError("release-gate warmed-query latency exceeds the regression limit")
    if candidate_warm["peak_memory_bytes"] > main_warm["peak_memory_bytes"] * 1.2:
        raise ValueError("release-gate warmed-query memory exceeds the regression limit")

    if report.get("recommendation") != gate["decision"]:
        raise ValueError("release-gate recommendation does not match the gate decision")
    require_nonempty_string(report.get("reproduction_command"), "reproduction_command")
    if not isinstance(report.get("limitations"), list) or not report["limitations"]:
        raise ValueError("release-gate limitations are missing")
    if not isinstance(report.get("host"), dict):
        raise ValueError("release-gate host metadata is missing")


def validate(report_path: Path, expected_candidate_commit: str | None = None) -> None:
    if not report_path.is_file():
        raise ValueError(f"release-gate report is missing: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate_report_evidence(report)
    inputs = report["inputs"]
    if inputs["freeze_manifest_sha256"] != sha256_file(FREEZE_MANIFEST):
        raise ValueError("release-gate freeze manifest digest is not the checked-in freeze")
    freeze = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    frozen_dev = json.loads(FROZEN_DEV_DATASET.read_text(encoding="utf-8"))
    split_hashes = freeze.get("splits", {})
    if inputs["dev_dataset_sha256"] != split_hashes.get("dev", {}).get("sha256"):
        raise ValueError("release-gate development dataset digest is not the frozen split")
    if inputs["dev_dataset_sha256"] != sha256_file(FROZEN_DEV_DATASET):
        raise ValueError("release-gate development dataset digest is not the checked-in dataset")
    frozen_corpus = frozen_dev.get("corpus")
    reported_dev_corpus = inputs["benchmark_corpus_compatibility"]["dev"]
    if not isinstance(frozen_corpus, dict) or any(
        reported_dev_corpus.get(field) != frozen_corpus.get(field)
        for field in ("parser_version", "source_revision", "source_digest")
    ):
        raise ValueError("release-gate benchmark corpus does not match frozen dev dataset")
    independent_manifest_path = inputs.get("independent_holdout_freeze_manifest_path")
    if not isinstance(independent_manifest_path, str):
        raise ValueError("release-gate independent holdout manifest path is missing")
    if Path(independent_manifest_path).resolve() != FRESH_HOLDOUT_MANIFEST.resolve():
        raise ValueError("release-gate independent holdout manifest path is not pinned")
    if sha256_file(FRESH_HOLDOUT_MANIFEST) != FRESH_HOLDOUT_MANIFEST_SHA256:
        raise ValueError("checked-in independent holdout manifest digest has changed")
    fresh_freeze = json.loads(FRESH_HOLDOUT_MANIFEST.read_text(encoding="utf-8"))
    if fresh_freeze.get("freeze_id") != FRESH_HOLDOUT_FREEZE_ID:
        raise ValueError("checked-in independent holdout freeze ID has changed")
    fresh_dataset_record = fresh_freeze.get("artifacts", {}).get("dataset", {})
    if inputs["holdout_dataset_sha256"] != fresh_dataset_record.get("sha256"):
        raise ValueError("release-gate holdout digest differs from the independent freeze")
    expected_holdout_path = (ROOT / fresh_dataset_record.get("path", "")).resolve()
    if Path(inputs.get("holdout_dataset_path", "")).resolve() != expected_holdout_path:
        raise ValueError("release-gate holdout path differs from the independent freeze")
    fresh_corpus = fresh_freeze.get("corpus", {})
    reported_holdout_corpus = inputs["benchmark_corpus_compatibility"]["holdout"]
    if any(
        reported_holdout_corpus.get(field) != fresh_corpus.get(field)
        for field in ("parser_version", "source_revision", "source_digest")
    ):
        raise ValueError("release-gate benchmark corpus does not match fresh holdout labels")
    protocol = report["protocol"]
    if protocol.get("query_network_policy") not in ALLOWED_NETWORK_POLICIES:
        raise ValueError("release-gate query network policy is not an approved offline wrapper")
    if expected_candidate_commit and report["builds"]["candidate"]["commit"] != expected_candidate_commit:
        raise ValueError("release-gate candidate commit does not match the release commit")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-candidate-commit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate(args.report.resolve(), args.expected_candidate_commit)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"release readiness failed: {error}")
        return 1
    print(f"release readiness passed: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
