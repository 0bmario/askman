#!/usr/bin/env python3
"""Validate the checked-in A/B report required before release publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE_MANIFEST = ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json"
ALLOWED_NETWORK_POLICIES = {
    "Linux unshare --net",
    "macOS sandbox-exec deny network*",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
QUALITY_METRICS = (
    "success_at_1",
    "success_at_3",
    "coverage",
    "incorrect_answered_tasks",
    "false_answers_on_unanswerable",
)
REQUIRED_PLATFORMS = {"common", "linux", "osx", "windows"}
POST_EVALUATION_PATHS = {
    "docs/reproducibility/artifacts/release-gate.json",
    "docs/reproducibility/release-gate.md",
}


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
        if summary["incorrect_answered_tasks"]["denominator"] > summary["answerable_tasks"]:
            raise ValueError(f"release-gate incorrect-answer denominator is inconsistent: {label}.{implementation}")


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


def validate_report_evidence(report: dict[str, object]) -> None:
    if report.get("schema_version") != 2:
        raise ValueError("release-gate report schema version is unsupported")
    if report.get("evidence_id") != "askman-main-vs-retrieval-v2-v1":
        raise ValueError("release-gate evidence id is unsupported")
    if report.get("status") != "complete":
        raise ValueError("release-gate report is not complete")
    evaluated_candidate_commit = report.get("evaluated_candidate_commit")
    if not isinstance(evaluated_candidate_commit, str) or not COMMIT_PATTERN.fullmatch(
        evaluated_candidate_commit
    ):
        raise ValueError("release-gate evaluated candidate commit is invalid")

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
        if label == "candidate" and commit != evaluated_candidate_commit:
            raise ValueError("release-gate evaluated candidate commit does not match candidate build")
        for field in ("cargo_lock_sha256", "binary_sha256"):
            require_digest(build.get(field), f"builds.{label}.{field}")
        if not isinstance(build.get("binary_bytes"), int) or build["binary_bytes"] <= 0:
            raise ValueError(f"release-gate binary size is invalid: {label}")
        command = build.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
            raise ValueError(f"release-gate build command is invalid: {label}")

    host = report.get("host")
    if isinstance(host, dict):
        host_platform = host.get("platform")
        if isinstance(host_platform, str) and any(
            marker in host_platform.lower() for marker in ("macos", "darwin")
        ):
            expected_runtime_path = "onnxruntime-osx-arm64-1.20.0/lib"
            runtime_paths = []
            for label in ("main", "candidate"):
                rpath = builds[label].get("ort_rpath")
                require_nonempty_string(rpath, f"builds.{label}.ort_rpath")
                if not rpath.endswith(expected_runtime_path):
                    raise ValueError(
                        f"release-gate macOS build did not use provisioned ONNX Runtime 1.20.0: {label}"
                    )
                runtime_paths.append(rpath)
            if runtime_paths[0] != runtime_paths[1]:
                raise ValueError("release-gate builds use different ONNX Runtime paths")

    quality = report.get("quality")
    if not isinstance(quality, dict):
        raise ValueError("release-gate quality evidence is missing")
    for split in ("dev", "holdout", "combined"):
        validate_quality_summary(quality.get(split), f"quality.{split}")

    combined = quality["combined"]
    main_summary = combined["main"]
    candidate_summary = combined["candidate"]
    if main_summary["answerable_tasks"] != candidate_summary["answerable_tasks"]:
        raise ValueError("release-gate implementations use different answerable task counts")
    if main_summary["unanswerable_tasks"] != candidate_summary["unanswerable_tasks"]:
        raise ValueError("release-gate implementations use different unanswerable task counts")
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
    interval = bootstrap.get("interval_95")
    if not isinstance(interval, dict):
        raise ValueError("release-gate bootstrap interval is missing")
    require_number(interval.get("lower"), "bootstrap.interval_95.lower")
    require_number(interval.get("upper"), "bootstrap.interval_95.upper")
    if interval["lower"] > interval["upper"]:
        raise ValueError("release-gate bootstrap interval is invalid")
    interval_contains_zero = interval["lower"] <= 0 <= interval["upper"]
    if bootstrap.get("interval_contains_zero") is not interval_contains_zero:
        raise ValueError("release-gate two-sided bootstrap diagnostic is inconsistent")
    require_number(
        bootstrap.get("one_sided_95_lower_bound"),
        "bootstrap.one_sided_95_lower_bound",
    )
    if bootstrap["one_sided_95_lower_bound"] < interval["lower"] or bootstrap[
        "one_sided_95_lower_bound"
    ] > interval["upper"]:
        raise ValueError("release-gate one-sided bootstrap bound is inconsistent")
    if bootstrap["one_sided_95_lower_bound"] <= 0:
        raise ValueError("release-gate one-sided bootstrap lower bound is not above zero")
    if bootstrap["paired_task_count"] != main_summary["answerable_tasks"]:
        raise ValueError("release-gate bootstrap task count does not match quality evidence")

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
                require_memory=False,
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
    if not isinstance(host, dict):
        raise ValueError("release-gate host metadata is missing")


def validate_release_lineage(
    evaluated_candidate_commit: str,
    expected_release_commit: str,
    repo_root: Path,
) -> None:
    repository = repo_root.resolve()
    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "merge-base",
            "--is-ancestor",
            evaluated_candidate_commit,
            expected_release_commit,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise ValueError(
            "release-gate evaluated candidate commit is not an ancestor of the release commit"
        )

    changed = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "diff",
            "--name-only",
            "-z",
            evaluated_candidate_commit,
            expected_release_commit,
        ],
        check=False,
        capture_output=True,
    )
    if changed.returncode != 0:
        raise ValueError("could not compare evaluated and release commit trees")
    paths = {
        item.decode("utf-8")
        for item in changed.stdout.split(b"\0")
        if item
    }
    unexpected = sorted(paths - POST_EVALUATION_PATHS)
    if unexpected:
        raise ValueError(
            "release commit changes files outside the post-evaluation evidence allowlist: "
            + ", ".join(unexpected)
        )


def validate(
    report_path: Path,
    expected_release_commit: str | None = None,
    *,
    repo_root: Path = ROOT,
) -> None:
    if not report_path.is_file():
        raise ValueError(f"release-gate report is missing: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate_report_evidence(report)
    inputs = report["inputs"]
    if inputs["freeze_manifest_sha256"] != sha256_file(FREEZE_MANIFEST):
        raise ValueError("release-gate freeze manifest digest is not the checked-in freeze")
    protocol = report["protocol"]
    if protocol.get("query_network_policy") not in ALLOWED_NETWORK_POLICIES:
        raise ValueError("release-gate query network policy is not an approved offline wrapper")
    if expected_release_commit:
        if not COMMIT_PATTERN.fullmatch(expected_release_commit):
            raise ValueError("release commit is invalid")
        validate_release_lineage(
            report["evaluated_candidate_commit"], expected_release_commit, repo_root
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-release-commit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate(args.report.resolve(), args.expected_release_commit)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"release readiness failed: {error}")
        return 1
    print(f"release readiness passed: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
