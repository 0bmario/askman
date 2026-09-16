import json
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json"
DEV_PATH = ROOT / "tests/fixtures/evaluation/frozen-dev-v2-expanded.json"
HOLDOUT_PATH = ROOT / "tests/fixtures/evaluation/frozen-holdout-v2-expanded.json"
CORPUS_PATH = ROOT / "tests/fixtures/tldr-evaluation-v2/manifest.json"
INTENTS_PATH = ROOT / "tests/fixtures/evaluation/task-intents-v2-expanded.json"
REPORT_PATHS = {
    "dev": ROOT / "docs/reproducibility/artifacts/evaluation-v2-expanded-dev-baseline.json",
    "holdout": ROOT / "docs/reproducibility/artifacts/evaluation-v2-expanded-holdout-comparison.json",
}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = load_module(
    "askman_evaluation_runner_expanded_test", ROOT / "scripts/evaluate_retrieval.py"
)
VALIDATOR = load_module(
    "askman_evaluation_validator_expanded_test",
    ROOT / "scripts/validate_evaluation_v2.py",
)


class ExpandedEvaluationV2Tests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.development = json.loads(DEV_PATH.read_text(encoding="utf-8"))
        self.holdout = json.loads(HOLDOUT_PATH.read_text(encoding="utf-8"))
        self.corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        self.intents = json.loads(INTENTS_PATH.read_text(encoding="utf-8"))

    def test_versioned_expanded_freeze_validates(self):
        VALIDATOR.validate_manifest(MANIFEST_PATH)
        self.assertEqual(
            self.manifest["previous_freeze_id"], "evaluation-v2-release-benchmark-v1"
        )

    def test_corpus_is_broader_and_publicly_pinned(self):
        self.assertGreaterEqual(len(self.corpus["files"]), 24)
        self.assertEqual(self.corpus["source"]["name"], "tldr-pages")
        self.assertEqual(self.corpus["source"]["license"]["name"], "MIT")
        self.assertIn(
            self.corpus["source"]["revision"], self.corpus["source"]["license"]["url"]
        )
        self.assertEqual(self.manifest["corpus_manifest"], "tests/fixtures/tldr-evaluation-v2/manifest.json")

    def test_expanded_pair_preserves_balance_platforms_and_multi_support(self):
        RUNNER.validate_dataset_pair(self.development, self.holdout)
        for dataset in (self.development, self.holdout):
            self.assertEqual(len(dataset["tasks"]), 60)
            self.assertEqual(sum(task["answerable"] for task in dataset["tasks"]), 30)
            self.assertEqual(
                {
                    platform: sum(task["platform"] == platform for task in dataset["tasks"])
                    for platform in ("common", "linux", "osx", "windows")
                },
                {"common": 15, "linux": 15, "osx": 15, "windows": 15},
            )
            self.assertEqual(
                len({task["family"] for task in dataset["tasks"]}), 12
            )
        self.assertTrue(
            any(
                len(task["acceptable_example_ids"]) > 1
                for task in self.development["tasks"] + self.holdout["tasks"]
                if task["answerable"]
            )
        )

    def test_intents_have_provenance_only_and_match_labels(self):
        VALIDATOR.validate_intents(self.intents, self.development, self.holdout)
        self.assertEqual(len(self.intents["tasks"]), 120)
        self.assertTrue(
            all(
                set(task) == {"id", "split", "family", "source_category", "intent"}
                for task in self.intents["tasks"]
            )
        )

    def test_hand_checks_cover_platform_behavior_support_and_abstention(self):
        task_ids = {
            task["id"]
            for task in self.development["tasks"] + self.holdout["tasks"]
        }
        checks = {
            check
            for item in self.manifest["hand_checks"]
            for check in item["checks"]
        }
        self.assertTrue(all(item["task_id"] in task_ids for item in self.manifest["hand_checks"]))
        self.assertTrue({"platform", "behavior", "acceptable_support", "abstention"} <= checks)

    def test_published_reports_pin_all_release_digests(self):
        for split, report_path in REPORT_PATHS.items():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            dataset_path = DEV_PATH if split == "dev" else HOLDOUT_PATH
            self.assertEqual(
                report["dataset_sha256"], VALIDATOR.RUNNER.sha256_file(dataset_path)
            )
            self.assertEqual(report["corpus"], self.manifest["corpus"])
            self.assertEqual(report["scorer"]["sha256"], self.manifest["scorer"]["sha256"])
            self.assertEqual(
                report["freeze_manifest"]["sha256"],
                VALIDATOR.RUNNER.sha256_file(MANIFEST_PATH),
            )
            self.assertEqual(report["split"], split)
            self.assertEqual(report["summary"]["tasks"], 60)
        holdout_report = json.loads(REPORT_PATHS["holdout"].read_text(encoding="utf-8"))
        self.assertTrue(holdout_report["holdout_access"]["authorized"])
        self.assertTrue(holdout_report["holdout_access"]["recorded"])


if __name__ == "__main__":
    unittest.main()
