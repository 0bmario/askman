import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "askman_evaluation_runner", ROOT / "scripts/evaluate_retrieval.py"
)
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


GOOD = "example-good"
OTHER = "example-other"
WRONG = "example-wrong"


def candidate(example_id):
    return RUNNER.Candidate(
        example_id, "page-1", "tool", "description", "example", "page.md",
        "source:page.md", "revision", "common", 1, 1, -1.0
    )


class EvaluationRunnerTests(unittest.TestCase):
    def test_frozen_dataset_is_60_tasks_with_whole_family_splits(self):
        dataset = RUNNER.load_json(ROOT / "tests/fixtures/evaluation/frozen-tasks-v1.json")
        RUNNER.validate_dataset(dataset)
        self.assertEqual(len(dataset["tasks"]), 60)
        self.assertEqual({task["split"] for task in dataset["tasks"]}, {"dev", "holdout"})

    def test_multiple_valid_answers_succeed_at_three(self):
        task = {"id": "multi", "answerable": True, "acceptable_example_ids": [GOOD, OTHER]}
        result = RUNNER.score_task(
            task, [candidate(WRONG), candidate(GOOD)], [candidate(WRONG), candidate(GOOD)]
        )
        self.assertFalse(result["success_at_1"])
        self.assertTrue(result["success_at_3"])
        self.assertTrue(result["candidate_recall"])

    def test_wrong_example_under_same_command_is_incorrect(self):
        task = {"id": "wrong", "answerable": True, "acceptable_example_ids": [GOOD]}
        result = RUNNER.score_task(task, [candidate(OTHER)], [candidate(OTHER)])
        self.assertFalse(result["success_at_1"])
        self.assertFalse(result["success_at_3"])
        self.assertTrue(result["incorrect_answer"])

    def test_no_result_answerable_task_is_miss_without_coverage(self):
        task = {"id": "none", "answerable": True, "acceptable_example_ids": [GOOD]}
        result = RUNNER.score_task(task, [], [])
        self.assertFalse(result["candidate_recall"])
        self.assertFalse(result["answered"])
        self.assertFalse(result["incorrect_answer"])

    def test_unanswerable_task_distinguishes_no_result_from_false_answer(self):
        task = {"id": "unknown", "answerable": False, "acceptable_example_ids": []}
        no_result = RUNNER.score_task(task, [], [])
        false_answer = RUNNER.score_task(task, [candidate(OTHER)], [candidate(OTHER)])
        self.assertFalse(no_result["false_answer"])
        self.assertTrue(false_answer["false_answer"])

    def test_dataset_labels_are_not_corpus_files(self):
        dataset_path = ROOT / "tests/fixtures/evaluation/frozen-tasks-v1.json"
        corpus_root = (ROOT / "tests/fixtures/tldr-full-corpus").resolve()
        self.assertNotIn(corpus_root, dataset_path.resolve().parents)

    def test_query_normalization_is_deterministic(self):
        self.assertEqual(RUNNER.normalized_tokens("CP, copy_copy cp"), ["copy_copy", "cp"])
        self.assertEqual(RUNNER.fts_query("CP, copy_copy cp"), '"copy_copy" AND "cp"')


if __name__ == "__main__":
    unittest.main()
