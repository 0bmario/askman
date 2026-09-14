import importlib.util
import sqlite3
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
        datasets = [
            RUNNER.load_json(ROOT / "tests/fixtures/evaluation/frozen-dev-v1.json"),
            RUNNER.load_json(ROOT / "tests/fixtures/evaluation/frozen-holdout-v1.json"),
        ]
        for dataset, split in zip(datasets, ("dev", "holdout")):
            RUNNER.validate_dataset(dataset, split)
            self.assertEqual(dataset["split"], split)
            self.assertEqual(len(dataset["tasks"]), 30)
        self.assertEqual(sum(len(dataset["tasks"]) for dataset in datasets), 60)
        self.assertEqual(
            {task["family"] for dataset in datasets for task in dataset["tasks"]},
            {
                "copy-dev",
                "search-dev",
                "edit-dev",
                "clipboard-dev",
                "windows-dev",
                "coverage-dev",
                "path-duplication",
                "tree-search",
                "editor-launch",
                "clipboard-transfer",
                "formatted-output",
                "missing-coverage",
            },
        )

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
        dataset_path = ROOT / "tests/fixtures/evaluation/frozen-dev-v1.json"
        corpus_root = (ROOT / "tests/fixtures/tldr-full-corpus").resolve()
        self.assertNotIn(corpus_root, dataset_path.resolve().parents)

    def test_labels_must_exist_in_the_selected_lexical_corpus(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript(
            """
            CREATE TABLE pages(page_id TEXT, page_name TEXT, platform TEXT, page_position INTEGER);
            CREATE TABLE examples(example_id TEXT, page_id TEXT);
            CREATE TABLE example_lexical(example_id TEXT);
            INSERT INTO pages VALUES ('page-1', 'tool', 'common', 1);
            INSERT INTO examples VALUES ('example-good', 'page-1');
            INSERT INTO example_lexical VALUES ('example-good');
            """
        )
        task = {
            "id": "bad-label",
            "answerable": True,
            "acceptable_example_ids": ["example-missing"],
            "platform": "common",
        }
        with self.assertRaisesRegex(ValueError, "example-missing"):
            RUNNER.validate_labels(connection, [task])
        connection.close()

    def test_query_normalization_is_deterministic(self):
        self.assertEqual(RUNNER.normalized_tokens("CP, copy_copy cp"), ["copy_copy", "cp"])
        self.assertEqual(RUNNER.fts_query("CP, copy_copy cp"), '"copy_copy" AND "cp"')


if __name__ == "__main__":
    unittest.main()
