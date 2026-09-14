import importlib.util
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "askman_heldout_evidence", ROOT / "scripts/run_heldout_evidence.py"
)
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


class HeldoutEvidenceRunnerTests(unittest.TestCase):
    def test_frozen_evidence_config_is_single_run_cpu_only_protocol(self):
        config = RUNNER.load_evidence_config(
            ROOT / "tests/fixtures/evaluation/heldout-evidence-config-v1.json"
        )
        self.assertEqual(config["quality"]["retrievers"], ["keyword", "hybrid"])
        self.assertEqual(config["quality"]["runs_per_retriever"], 1)
        self.assertTrue(config["quality"]["no_holdout_tuning_or_rerun"])
        self.assertEqual(config["execution_provider"], "CPU only; no GPU")
        self.assertEqual(
            config["dataset_sha256"], RUNNER.FROZEN_HOLDOUT_DATASET_SHA256
        )

    def test_hybrid_performance_query_runs_the_end_to_end_path(self):
        candidate = SimpleNamespace(keyword_budget=8, dense_budget=8)
        client = mock.Mock()
        connection = object()
        with mock.patch.object(
            RUNNER.evaluator, "fetch_candidates", return_value=[]
        ) as fetch, mock.patch.object(
            RUNNER.evaluator, "fuse_candidates", return_value=[]
        ) as fuse, mock.patch.object(
            RUNNER.evaluator, "hybrid_results", return_value=[]
        ) as display:
            RUNNER.run_hybrid_query(
                connection,
                client,
                {"question": "open a file", "platform": "common"},
                candidate,
            )
        fetch.assert_called_once_with(connection, "open a file", "common", 8)
        client.query.assert_called_once_with("open a file", "common", 8)
        fuse.assert_called_once()
        display.assert_called_once()

    def test_percentile_uses_nearest_rank_and_explicit_small_sample_limit(self):
        self.assertEqual(RUNNER.percentile([1, 2, 3, 4, 5], 0.50), 3)
        self.assertEqual(RUNNER.percentile([1, 2, 3, 4, 5], 0.95), 5)
        self.assertIsNone(RUNNER.percentile([], 0.95))

    def test_build_metadata_parses_numeric_and_text_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build.txt"
            path.write_text("build_time_ms=12\nhardware=Apple M\n", encoding="utf-8")
            self.assertEqual(
                RUNNER.parse_key_value_output(path),
                {"build_time_ms": 12, "hardware": "Apple M"},
            )

    def test_representatives_preserve_success_and_abstention_examples(self):
        quality = {
            "keyword": {
                "tasks": [
                    {
                        "task_id": "success",
                        "displayed_example_ids": ["good"],
                        "candidate_example_ids": ["good"],
                        "success_at_3": True,
                        "answered": True,
                        "incorrect_answer": False,
                        "false_answer": False,
                    },
                    {
                        "task_id": "abstain",
                        "displayed_example_ids": [],
                        "candidate_example_ids": [],
                        "success_at_3": False,
                        "answered": False,
                        "incorrect_answer": False,
                        "false_answer": False,
                    },
                ]
            }
        }
        representative = RUNNER.representatives(quality)["keyword"]
        self.assertEqual(representative["successes"][0]["task_id"], "success")
        self.assertEqual(representative["correct_abstentions"][0]["task_id"], "abstain")
        self.assertEqual(representative["failures"], [])

    def test_config_rejects_holdout_rerun_protocol(self):
        config = json.loads(
            (ROOT / "tests/fixtures/evaluation/heldout-evidence-config-v1.json").read_text()
        )
        config["quality"]["runs_per_retriever"] = 2
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly once"):
                RUNNER.load_evidence_config(path)

    def test_config_rejects_an_unpinned_holdout_dataset(self):
        config = json.loads(
            (ROOT / "tests/fixtures/evaluation/heldout-evidence-config-v1.json").read_text()
        )
        config["dataset_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pin the committed holdout"):
                RUNNER.load_evidence_config(path)

    def test_committed_evidence_config_digest_is_pinned(self):
        self.assertEqual(
            RUNNER.sha256_file(
                ROOT / "tests/fixtures/evaluation/heldout-evidence-config-v1.json"
            ),
            RUNNER.FROZEN_EVIDENCE_CONFIG_SHA256,
        )

    def test_run_rejects_modified_holdout_before_quality_evaluation(self):
        dataset = json.loads(
            (ROOT / "tests/fixtures/evaluation/frozen-holdout-v1.json").read_text()
        )
        dataset["tasks"][0]["question"] = "modified after holdout inspection"
        with tempfile.TemporaryDirectory() as directory:
            dataset_path = Path(directory) / "modified-holdout.json"
            dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
            args = SimpleNamespace(
                artifact=Path(directory) / "missing.db",
                manifest=ROOT / "tests/fixtures/tldr-full-corpus/manifest.json",
                dataset=dataset_path,
                hybrid_config=ROOT / "tests/fixtures/evaluation/hybrid-config-v1.json",
                evidence_config=ROOT / "tests/fixtures/evaluation/heldout-evidence-config-v1.json",
                dense_helper=Path(directory) / "missing-helper",
                model_cache=Path(directory) / "missing-model-cache",
                build_metadata=None,
                dense_build_metadata=None,
                network_probe=None,
                output=Path(directory) / "report.json",
            )
            with self.assertRaisesRegex(ValueError, "not the committed frozen split"):
                RUNNER.run(args)


if __name__ == "__main__":
    unittest.main()
