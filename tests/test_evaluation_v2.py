import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = load_module(
    "askman_evaluation_runner_v2_test", ROOT / "scripts/evaluate_retrieval.py"
)
VALIDATOR = load_module(
    "askman_evaluation_v2_validator_test", ROOT / "scripts/validate_evaluation_v2.py"
)


class EvaluationV2Tests(unittest.TestCase):
    def setUp(self):
        self.development = RUNNER.load_json(
            ROOT / "tests/fixtures/evaluation/frozen-dev-v2.json"
        )
        self.holdout = RUNNER.load_json(
            ROOT / "tests/fixtures/evaluation/frozen-holdout-v2.json"
        )

    def test_committed_v2_freeze_manifest_validates(self):
        VALIDATOR.validate_manifest(
            ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest.json"
        )

    def test_v2_splits_are_balanced_and_platform_complete(self):
        RUNNER.validate_dataset_pair(self.development, self.holdout)
        for dataset in (self.development, self.holdout):
            self.assertEqual(len(dataset["tasks"]), 60)
            self.assertEqual(sum(task["answerable"] for task in dataset["tasks"]), 30)
            self.assertEqual(
                {task["platform"] for task in dataset["tasks"]},
                {"common", "linux", "osx", "windows"},
            )
            self.assertEqual(
                {
                    platform: sum(task["platform"] == platform for task in dataset["tasks"])
                    for platform in ("common", "linux", "osx", "windows")
                },
                {"common": 15, "linux": 15, "osx": 15, "windows": 15},
            )

    def test_v2_intents_contain_only_provenance_fields(self):
        intents = json.loads(
            (ROOT / "tests/fixtures/evaluation/task-intents-v2.json").read_text(
                encoding="utf-8"
            )
        )
        VALIDATOR.validate_intents(intents, self.development, self.holdout)
        self.assertTrue(
            all(
                set(task) == {"id", "split", "family", "source_category", "intent"}
                for task in intents["tasks"]
            )
        )

    def test_hand_checked_scorer_cases_cover_release_benchmark_outcomes(self):
        def candidate(example_id):
            return RUNNER.Candidate(
                example_id=example_id,
                page_id="page-1",
                command="tool",
                page_description="description",
                example_description="example",
                source_path="page.md",
                source_ref="source:page.md",
                source_revision="revision",
                platform="common",
                page_position=1,
                example_position=1,
                ranking_score=-1.0,
            )

        good = candidate("example-good")
        other = candidate("example-other")
        wrong = candidate("example-wrong")
        multiple = RUNNER.score_task(
            {"id": "multiple", "answerable": True, "acceptable_example_ids": ["example-good", "example-other"]},
            [wrong, good],
            [wrong, good],
        )
        wrong_command_example = RUNNER.score_task(
            {"id": "wrong", "answerable": True, "acceptable_example_ids": ["example-good"]},
            [other],
            [other],
        )
        no_result = RUNNER.score_task(
            {"id": "none", "answerable": True, "acceptable_example_ids": ["example-good"]},
            [],
            [],
        )
        correct_abstention = RUNNER.score_task(
            {"id": "abstain", "answerable": False, "acceptable_example_ids": []},
            [],
            [],
        )
        false_answer = RUNNER.score_task(
            {"id": "false", "answerable": False, "acceptable_example_ids": []},
            [wrong],
            [wrong],
        )

        self.assertTrue(multiple["success_at_3"])
        self.assertTrue(wrong_command_example["incorrect_answer"])
        self.assertFalse(no_result["answered"])
        self.assertFalse(correct_abstention["false_answer"])
        self.assertTrue(false_answer["false_answer"])


if __name__ == "__main__":
    unittest.main()
