import argparse
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


def candidate(
    example_id,
    page_id="page-1",
    source_path="page.md",
    ranking_score=-1.0,
    platform="common",
):
    return RUNNER.Candidate(
        example_id, page_id, "tool", "description", "example", source_path,
        "source:" + source_path, "revision", platform, 1, 1, ranking_score
    )


def hybrid_config(candidate_id="test", weak_match_cutoff=0.0, budget=3):
    return RUNNER.HybridCandidateConfig(
        candidate_id=candidate_id,
        rrf_k=60,
        keyword_weight=1.0,
        dense_weight=1.0,
        keyword_budget=budget,
        dense_budget=budget,
        weak_match_cutoff=weak_match_cutoff,
    )


class EvaluationRunnerTests(unittest.TestCase):
    def test_frozen_dev_dataset_has_30_tasks_and_whole_families(self):
        dataset = RUNNER.load_json(ROOT / "tests/fixtures/evaluation/frozen-dev-v1.json")
        RUNNER.validate_dataset(dataset, "dev")
        self.assertEqual(dataset["split"], "dev")
        self.assertEqual(len(dataset["tasks"]), 30)
        self.assertEqual(
            {task["family"] for task in dataset["tasks"]},
            {
                "copy-dev",
                "search-dev",
                "clipboard-dev",
                "coverage-dev",
                "audit-dev",
                "platform-dev",
            },
        )

    def test_dev_intents_match_dev_task_ids_without_labels(self):
        dataset = RUNNER.load_json(ROOT / "tests/fixtures/evaluation/frozen-dev-v1.json")
        intents = RUNNER.load_json(
            ROOT / "tests/fixtures/evaluation/task-intents-v1.json"
        )
        dev_intents = [
            entry for entry in intents["tasks"] if entry["split"] == "dev"
        ]
        self.assertEqual(
            {entry["id"] for entry in dev_intents},
            {task["id"] for task in dataset["tasks"]},
        )
        self.assertTrue(
            all(
                set(entry) == {"id", "split", "family", "intent"}
                for entry in dev_intents
            )
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

    def test_query_normalization_covers_command_names_punctuation_and_flags(self):
        question = "git-commit --amend, --message='fix.it'"
        self.assertEqual(
            RUNNER.normalized_tokens(question),
            ["amend", "commit", "fix", "git", "it", "message"],
        )
        self.assertEqual(
            RUNNER.fts_query(question),
            '"amend" AND "commit" AND "fix" AND "git" AND "it" AND "message"',
        )

    def test_hybrid_fusion_rewards_agreement_and_keeps_candidate_recall(self):
        config = hybrid_config()
        keyword = [
            candidate("shared", page_id="page-shared"),
            candidate("keyword-only", page_id="page-keyword"),
        ]
        dense = [
            candidate("dense-only", page_id="page-dense"),
            candidate("shared", page_id="page-shared"),
        ]

        fused = RUNNER.fuse_candidates(keyword, dense, config)

        self.assertEqual(
            [item.example_id for item in fused],
            ["shared", "dense-only", "keyword-only"],
        )
        self.assertEqual(
            {item.example_id for item in fused},
            {"shared", "keyword-only", "dense-only"},
        )

    def test_hybrid_budgets_count_best_page_candidates(self):
        config = hybrid_config(budget=2)
        fused = RUNNER.fuse_candidates(
            [
                candidate("first", page_id="page-a"),
                candidate("second", page_id="page-a"),
                candidate("third", page_id="page-b"),
            ],
            [candidate("third", page_id="page-b")],
            config,
        )

        self.assertEqual(
            {item.example_id for item in fused}, {"first", "third"}
        )

    def test_hybrid_cutoff_displays_distinct_pages_and_can_return_none(self):
        config = hybrid_config(weak_match_cutoff=0.5)
        candidates = RUNNER.fuse_candidates(
            [candidate("shared", page_id="page-a"), candidate("same-page", page_id="page-a")],
            [candidate("shared", page_id="page-a"), candidate("other", page_id="page-b")],
            config,
        )

        displayed = RUNNER.hybrid_results(candidates, config)

        self.assertEqual([item.example_id for item in displayed], ["shared"])
        self.assertEqual(len({item.page_id for item in displayed}), len(displayed))

        no_match = hybrid_config(
            candidate_id="test-no-match", weak_match_cutoff=1.0
        )
        self.assertEqual(RUNNER.hybrid_results(candidates, no_match), [])

    def test_hybrid_rejects_conflicting_candidate_identity(self):
        config = hybrid_config()
        with self.assertRaisesRegex(ValueError, "candidate identity mismatch"):
            RUNNER.fuse_candidates(
                [candidate("shared", page_id="page-a")],
                [candidate("shared", page_id="page-b")],
                config,
            )

    def test_frozen_hybrid_config_declares_selection_and_policy(self):
        dataset = RUNNER.load_json(ROOT / "tests/fixtures/evaluation/frozen-dev-v1.json")
        config = RUNNER.load_hybrid_config(
            ROOT / "tests/fixtures/evaluation/hybrid-config-v1.json"
        )
        self.assertTrue(config.frozen)
        self.assertEqual(config.selected.candidate_id, config.selected_candidate_id)
        self.assertEqual(config.selection_rule["primary_metric"], "success_at_3")
        self.assertEqual(len(config.candidates), 5)
        self.assertEqual(
            RUNNER.select_development_candidate(config), config.selected_candidate_id
        )
        RUNNER.validate_hybrid_config_for_dataset(config, dataset)

        changed_dataset = dict(dataset)
        changed_dataset["corpus"] = dict(dataset["corpus"])
        changed_dataset["corpus"]["source_digest"] = "changed"
        with self.assertRaisesRegex(ValueError, "corpus identity"):
            RUNNER.validate_hybrid_config_for_dataset(config, changed_dataset)

    def test_hybrid_config_binds_the_dense_recipe(self):
        config = RUNNER.load_hybrid_config(
            ROOT / "tests/fixtures/evaluation/hybrid-config-v1.json"
        )
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE artifact_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO artifact_metadata VALUES ('dense_embedding_text_recipe', 'description')"
        )
        RUNNER.validate_hybrid_config_for_artifact(config, connection)
        connection.execute(
            "UPDATE artifact_metadata SET value = 'description-plus-parent'"
        )
        with self.assertRaisesRegex(ValueError, "dense recipe"):
            RUNNER.validate_hybrid_config_for_artifact(config, connection)
        connection.close()

    def test_dense_retrieval_rejects_holdout_before_loading_labels(self):
        args = argparse.Namespace(
            retriever="dense",
            split="holdout",
            dataset=ROOT / "does-not-exist.json",
        )
        with self.assertRaisesRegex(ValueError, "development-only"):
            RUNNER.run(args)

    def test_hybrid_retrieval_rejects_holdout_without_explicit_access(self):
        args = argparse.Namespace(
            retriever="hybrid",
            split="holdout",
            allow_holdout=False,
            dataset=ROOT / "does-not-exist.json",
        )
        with self.assertRaisesRegex(ValueError, "holdout labels require"):
            RUNNER.run(args)

    def test_hybrid_options_are_rejected_for_other_retrievers(self):
        args = argparse.Namespace(
            retriever="keyword",
            split="dev",
            dataset=ROOT / "does-not-exist.json",
            hybrid_candidate="rrf-k60-b8-cutoff-0.50",
        )
        with self.assertRaisesRegex(ValueError, "only valid with --retriever hybrid"):
            RUNNER.run(args)


if __name__ == "__main__":
    unittest.main()
