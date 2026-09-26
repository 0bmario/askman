import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_release_gate import (
    FRESH_HOLDOUT_DATASET_SHA256,
    FRESH_HOLDOUT_FREEZE_ID,
    FRESH_HOLDOUT_MANIFEST,
    FRESH_HOLDOUT_MANIFEST_SHA256,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json"
DEV = ROOT / "tests/fixtures/evaluation/frozen-dev-v2-expanded.json"


def freeze_digest() -> str:
    return hashlib.sha256(FREEZE.read_bytes()).hexdigest()


def passing_report() -> dict:
    def summary(success_at_1_count: int, success_at_3_count: int) -> dict:
        answered_answerable = 10
        return {
            "tasks": 12,
            "answerable_tasks": 10,
            "unanswerable_tasks": 2,
            "success_at_1": {"count": success_at_1_count, "denominator": 10},
            "success_at_3": {"count": success_at_3_count, "denominator": 10},
            "coverage": {"count": 10, "denominator": 12},
            "incorrect_answered_tasks": {
                "count": answered_answerable - success_at_3_count,
                "denominator": answered_answerable,
            },
            "false_answers_on_unanswerable": {"count": 0, "denominator": 2},
        }

    def quality_summary() -> dict:
        main = summary(4, 7)
        candidate = summary(6, 8)
        return {
            "main": main,
            "candidate": candidate,
            "platform": {
                name: {"main": main, "candidate": candidate}
                for name in ("common", "linux", "osx", "windows")
            },
            "family": {
                name: {
                    "main": summary(2, 3),
                    "candidate": summary(3, 4),
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
    frozen_dev = json.loads(DEV.read_text(encoding="utf-8"))
    dev_corpus = {
        field: frozen_dev["corpus"][field]
        for field in ("parser_version", "source_revision", "source_digest")
    }
    fresh_manifest = json.loads(FRESH_HOLDOUT_MANIFEST.read_text(encoding="utf-8"))
    holdout_corpus = {
        "parser_version": fresh_manifest["corpus"]["parser_version"],
        "source_revision": fresh_manifest["corpus"]["source_revision"],
        "source_digest": fresh_manifest["corpus"]["source_digest"],
        "matches_candidate_bundle": True,
    }
    record_equivalence = {
        "records_identical": True,
        "reference_parser_version": dev_corpus["parser_version"],
        "candidate_parser_version": holdout_corpus["parser_version"],
        "source_revision": dev_corpus["source_revision"],
        "source_digest": dev_corpus["source_digest"],
        "reference_example_count": 142,
        "candidate_example_count": 142,
        "reference_inventory_sha256": "d" * 64,
        "candidate_inventory_sha256": "d" * 64,
    }
    compatible_dev_corpus = {
        **dev_corpus,
        "matches_candidate_bundle": True,
        "record_equivalence": record_equivalence,
    }
    model_asset_path = "models--Qdrant--all-MiniLM-L6-v2-onnx/refs/main"
    model_asset_digest = "c" * 64
    return {
        "schema_version": 4,
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
            "holdout_freeze_id": FRESH_HOLDOUT_FREEZE_ID,
        },
        "inputs": {
            "freeze_manifest_sha256": freeze_digest(),
            "benchmark_id": "askman-evaluation-v2",
            "freeze_id": "freeze-v1",
            "independent_holdout_freeze_id": FRESH_HOLDOUT_FREEZE_ID,
            "independent_holdout_freeze_manifest_path": str(FRESH_HOLDOUT_MANIFEST),
            "independent_holdout_freeze_manifest_sha256": FRESH_HOLDOUT_MANIFEST_SHA256,
            "bundle": {
                "bundle_id": "matching-bundle-v2:test",
                "manifest_sha256": digest,
                "bundle_tree_sha256": digest,
                "staged_tree_sha256": digest,
            },
            "main_data_dir_tree_sha256": digest,
            "main_data_file_sha256": {
                "commands.db": "ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db",
                f"models/{model_asset_path}": model_asset_digest,
            },
            "bundle_file_sha256": {
                "manifest.json": digest,
                f"model-cache/{model_asset_path}": model_asset_digest,
            },
            "input_compatibility": {
                "candidate_parser_version": holdout_corpus["parser_version"],
                "candidate_source_revision": dev_corpus["source_revision"],
                "candidate_source_digest": dev_corpus["source_digest"],
                "main_database_sha256": "ef3b96cc8ee5a9effa08d9a5e8366e3d92e9b3c7866493568fe2248d379819db",
                "main_database_matches_pinned_baseline": True,
                "visible_corpus_example_count": 142,
                "visible_corpus_examples_sha256": digest,
                "model_asset_count": 1,
                "model_asset_digests": {model_asset_path: model_asset_digest},
                "model_assets_match": True,
            },
            "benchmark_corpus_compatibility": {
                "dev": compatible_dev_corpus,
                "holdout": holdout_corpus,
            },
            "dev_dataset_sha256": hashlib.sha256(DEV.read_bytes()).hexdigest(),
            "holdout_dataset_sha256": FRESH_HOLDOUT_DATASET_SHA256,
            "holdout_dataset_path": str(
                ROOT / fresh_manifest["artifacts"]["dataset"]["path"]
            ),
            "gate_runner_sha256": hashlib.sha256(
                (ROOT / "scripts/run_release_gate.py").read_bytes()
            ).hexdigest(),
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
            "seed": 33031,
            "resamples": 10_000,
            "paired_task_count": 10,
            "observed_success_at_1_gain": 0.2,
            "one_sided_95_lower_bound": 0.05,
            "interval_95": {"lower": 0.05, "upper": 0.25},
            "interval_contains_zero": False,
        },
        "independent_holdout_bootstrap": {
            "seed": 33031,
            "resamples": 10_000,
            "paired_task_count": 10,
            "observed_success_at_1_gain": 0.2,
            "one_sided_95_lower_bound": 0.05,
            "interval_95": {"lower": 0.05, "upper": 0.25},
            "interval_contains_zero": False,
        },
        "independent_holdout_gate": {
            "passed": True,
            "decision": "better_askman",
            "success_at_1_gain": 0.2,
            "reasons": [],
        },
        "performance": performance(),
        "execution": {"main": [], "candidate": []},
        "gate": {
            "passed": True,
            "decision": "better_askman",
            "overall_success_at_1_gain": 0.2,
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

    def test_fresh_process_memory_regression_is_rejected(self):
        document = passing_report()
        document["performance"]["candidate"]["dev"]["fresh_process"][
            "peak_memory_bytes"
        ] = 2
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "dev fresh-process memory exceeds the regression limit"
            ):
                validate(report, "b" * 40)

    def test_schema_four_binds_report_to_the_gate_runner(self):
        document = passing_report()
        document["schema_version"] = 4
        document["inputs"]["gate_runner_sha256"] = hashlib.sha256(
            (ROOT / "scripts/run_release_gate.py").read_bytes()
        ).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            validate(report, "b" * 40)

        document["inputs"]["gate_runner_sha256"] = "d" * 64
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "runner digest"):
                validate(report, "b" * 40)

    def test_positive_one_sided_bound_allows_two_sided_interval_to_include_zero(self):
        document = passing_report()
        document["bootstrap"]["one_sided_95_lower_bound"] = 0.01
        document["bootstrap"]["interval_95"]["lower"] = 0.0
        document["bootstrap"]["interval_contains_zero"] = True
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            validate(report, "b" * 40)

    def test_nonpositive_one_sided_bound_is_rejected(self):
        document = passing_report()
        document["bootstrap"]["one_sided_95_lower_bound"] = 0.0
        document["bootstrap"]["interval_95"]["lower"] = 0.0
        document["bootstrap"]["interval_contains_zero"] = True
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one-sided"):
                validate(report, "b" * 40)

    def test_inconclusive_report_is_rejected(self):
        document = passing_report()
        document["recommendation"] = "inconclusive"
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(report)

    def test_input_compatibility_evidence_is_required(self):
        document = passing_report()
        del document["inputs"]["input_compatibility"]
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "input compatibility"):
                validate(report)

    def test_benchmark_corpus_must_match_frozen_dev_dataset(self):
        document = passing_report()
        candidate_digest = "b" * 64
        document["inputs"]["input_compatibility"]["candidate_source_digest"] = candidate_digest
        for split in ("dev", "holdout"):
            document["inputs"]["benchmark_corpus_compatibility"][split][
                "source_digest"
            ] = candidate_digest
        document["inputs"]["benchmark_corpus_compatibility"]["dev"][
            "record_equivalence"
        ]["source_digest"] = candidate_digest
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match frozen dev dataset"):
                validate(report, "b" * 40)

    def test_parser_version_change_requires_exact_record_equivalence(self):
        document = passing_report()
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            validate(report, "b" * 40)

        document["inputs"]["benchmark_corpus_compatibility"]["dev"][
            "record_equivalence"
        ]["records_identical"] = False
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "record equivalence is invalid"):
                validate(report, "b" * 40)

    def test_model_asset_claim_must_match_recorded_file_digests(self):
        document = passing_report()
        document["inputs"]["bundle_file_sha256"][
            "model-cache/models--Qdrant--all-MiniLM-L6-v2-onnx/refs/main"
        ] = "d" * 64
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "model asset digest"):
                validate(report, "b" * 40)

    def test_unpinned_main_database_is_rejected(self):
        document = passing_report()
        document["inputs"]["input_compatibility"][
            "main_database_matches_pinned_baseline"
        ] = False
        document["inputs"]["input_compatibility"]["main_database_sha256"] = "a" * 64
        document["inputs"]["main_data_file_sha256"]["commands.db"] = "a" * 64
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match the pinned evaluation baseline"):
                validate(report, "b" * 40)

    def test_incomplete_evidence_is_rejected(self):
        document = passing_report()
        document["quality"]["combined"] = {}
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(report)

    def test_incorrect_answer_denominator_must_match_answered_answerable_tasks(self):
        document = passing_report()
        document["quality"]["dev"]["main"]["incorrect_answered_tasks"] = {
            "count": 0,
            "denominator": 0,
        }
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incorrect-answer denominator"):
                validate(report)

    def test_incorrect_answer_count_must_match_answered_answerable_failures(self):
        document = passing_report()
        summary = document["quality"]["dev"]["main"]
        summary["success_at_3"]["count"] = 9
        summary["incorrect_answered_tasks"]["count"] = 0
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incorrect-answer count"):
                validate(report)

    def test_success_at_1_cannot_exceed_success_at_3(self):
        document = passing_report()
        summary = document["quality"]["dev"]["main"]
        summary["success_at_1"]["count"] = 10
        summary["success_at_3"]["count"] = 9
        summary["incorrect_answered_tasks"]["count"] = 1
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "release-gate.json"
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Success@1 exceeds Success@3"):
                validate(report)

    def test_implementations_must_use_matching_subgroup_task_counts(self):
        for subgroup_kind, subgroup_name in (("platform", "linux"), ("family", "family-a")):
            with self.subTest(subgroup=f"{subgroup_kind}.{subgroup_name}"):
                document = passing_report()
                summary = document["quality"]["combined"][subgroup_kind][subgroup_name]["candidate"]
                summary["tasks"] = 13
                summary["answerable_tasks"] = 11
                summary["success_at_1"]["denominator"] = 11
                summary["success_at_3"]["denominator"] = 11
                summary["success_at_3"]["count"] = 11
                summary["coverage"]["denominator"] = 13
                summary["coverage"]["count"] = 11
                summary["incorrect_answered_tasks"]["denominator"] = 11
                summary["incorrect_answered_tasks"]["count"] = 0
                if subgroup_kind == "family":
                    document["quality"]["combined"]["family"][subgroup_name][
                        "success_at_1_gain"
                    ] = 1 / 11
                with tempfile.TemporaryDirectory() as directory:
                    report = Path(directory) / "release-gate.json"
                    report.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "different task counts"):
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
            summary["false_answers_on_unanswerable"] = {
                "count": summary["coverage"]["count"],
                "denominator": summary["unanswerable_tasks"],
            }
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
