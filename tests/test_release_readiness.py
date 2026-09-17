import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_release_gate import validate


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json"


def freeze_digest() -> str:
    return hashlib.sha256(FREEZE.read_bytes()).hexdigest()


def passing_report() -> dict:
    def summary(success_at_1_count: int) -> dict:
        metric = {"count": 10, "denominator": 10}
        return {
            "tasks": 12,
            "answerable_tasks": 10,
            "unanswerable_tasks": 2,
            "success_at_1": {"count": success_at_1_count, "denominator": 10},
            "success_at_3": metric,
            "coverage": {"count": 10, "denominator": 12},
            "incorrect_answered_tasks": {"count": 0, "denominator": 10},
            "false_answers_on_unanswerable": {"count": 0, "denominator": 2},
        }

    def quality_summary() -> dict:
        return {
            "main": summary(0),
            "candidate": summary(1),
            "platform": {
                name: {"main": summary(0), "candidate": summary(1)}
                for name in ("common", "linux", "osx", "windows")
            },
            "family": {
                name: {
                    "main": summary(0),
                    "candidate": summary(1),
                    "success_at_1_gain": 0.1,
                }
                for name in ("family-a", "family-b")
            },
            "failures": {"main": [], "candidate": []},
        }

    def latency() -> dict:
        return {
            "sample_count": 1,
            "p50_ms": 1.0,
            "p95_ms": 1.0,
            "peak_memory_bytes": 1,
            "memory_sample_count": 1,
        }

    def performance() -> dict:
        return {
            label: {
                "dev": {"fresh_process": latency()},
                "holdout": {"fresh_process": latency()},
                "warmed_query": latency(),
            }
            for label in ("main", "candidate")
        }

    digest = "a" * 64
    return {
        "schema_version": 1,
        "evidence_id": "askman-main-vs-retrieval-v2-v1",
        "status": "complete",
        "recommendation": "better_askman",
        "protocol": {
            "development_and_holdout": True,
            "no_holdout_tuning": True,
            "setup_download_separate": True,
            "holdout_access_authorized": True,
            "main_ref": "main",
            "candidate_ref": "retrieval-v2",
            "timing_policy": "fresh process",
            "query_network_policy": "Linux unshare --net",
        },
        "inputs": {
            "freeze_manifest_sha256": freeze_digest(),
            "benchmark_id": "askman-evaluation-v2",
            "freeze_id": "freeze-v1",
            "bundle": {
                "bundle_id": "matching-bundle-v2:test",
                "manifest_sha256": digest,
                "bundle_tree_sha256": digest,
                "staged_tree_sha256": digest,
            },
            "main_data_dir_tree_sha256": digest,
            "main_data_file_sha256": {"commands.db": digest},
            "bundle_file_sha256": {"manifest.json": digest},
            "dev_dataset_sha256": digest,
            "holdout_dataset_sha256": digest,
            "scorer_sha256": digest,
        },
        "builds": {
            "main": {
                "ref": "main",
                "commit": "a" * 40,
                "cargo_lock_sha256": digest,
                "binary_sha256": digest,
                "binary_bytes": 1,
                "command": ["cargo", "build"],
            },
            "candidate": {
                "ref": "retrieval-v2",
                "commit": "b" * 40,
                "cargo_lock_sha256": digest,
                "binary_sha256": digest,
                "binary_bytes": 1,
                "command": ["cargo", "build"],
            },
        },
        "quality": {
            "dev": quality_summary(),
            "holdout": quality_summary(),
            "combined": quality_summary(),
        },
        "bootstrap": {
            "seed": 20250301,
            "resamples": 10_000,
            "paired_task_count": 10,
            "observed_success_at_1_gain": 0.1,
            "interval_95": {"lower": 0.05, "upper": 0.15},
            "interval_contains_zero": False,
        },
        "performance": performance(),
        "execution": {"main": [], "candidate": []},
        "gate": {
            "passed": True,
            "decision": "better_askman",
            "overall_success_at_1_gain": 0.1,
            "positive_family_count": 2,
            "family_regressions": [],
            "reasons": [],
        },
        "reproduction_command": "python scripts/run_release_gate.py ...",
        "limitations": ["synthetic test report"],
        "host": {"platform": "test"},
    }


class ReleaseReadinessTests(unittest.TestCase):
    def test_passing_report_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(passing_report()), encoding="utf-8")
            validate(report, "b" * 40)

    def test_inconclusive_report_is_rejected(self):
        document = passing_report()
        document["recommendation"] = "inconclusive"
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(report)

    def test_incomplete_evidence_is_rejected(self):
        document = passing_report()
        document["quality"]["combined"] = {}
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(report)

    def test_zero_answerable_family_is_allowed(self):
        document = passing_report()
        family = document["quality"]["combined"]["family"]["family-a"]
        for implementation in ("main", "candidate"):
            summary = family[implementation]
            summary["answerable_tasks"] = 0
            summary["unanswerable_tasks"] = summary["tasks"]
            summary["success_at_1"] = {"count": 0, "denominator": 0}
            summary["success_at_3"] = {"count": 0, "denominator": 0}
            summary["incorrect_answered_tasks"] = {"count": 0, "denominator": 0}
            summary["false_answers_on_unanswerable"] = {"count": 0, "denominator": summary["unanswerable_tasks"]}
        family["success_at_1_gain"] = 0.0
        document["quality"]["combined"]["family"]["family-c"] = document["quality"]["combined"]["family"]["family-b"]
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            validate(report, "b" * 40)

    def test_platform_quality_regression_is_rejected(self):
        document = passing_report()
        document["quality"]["combined"]["candidate"]["success_at_3"]["count"] = 0
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(report)
