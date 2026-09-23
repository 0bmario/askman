import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "askman_release_gate", ROOT / "scripts/run_release_gate.py"
)
GATE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
import sys

sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)


def task(task_id, family, platform, answerable=True):
    return {
        "id": task_id,
        "family": family,
        "platform": platform,
        "answerable": answerable,
        "acceptable_example_ids": ["good"] if answerable else [],
        "question": task_id,
    }


class ReleaseGateTests(unittest.TestCase):
    def test_parser_maps_user_visible_example_pairs(self):
        output = """
        \x1b[32mls\x1b[0m
        List files.

        \x1b[4mExamples:\x1b[0m
          List one per line.
           ls -1
        """
        self.assertEqual(
            GATE.parse_displayed_results(output),
            [{"description": "List one per line.", "command": "ls -1"}],
        )

    def test_parser_keeps_all_examples_in_one_block(self):
        output = """
        Examples:
          List one per line.
           ls -1

          List all entries.
           ls -a
        """
        self.assertEqual(
            GATE.parse_displayed_results(output),
            [
                {"description": "List one per line.", "command": "ls -1"},
                {"description": "List all entries.", "command": "ls -a"},
            ],
        )

    def test_unmapped_visible_result_counts_as_an_answer(self):
        result = GATE.score_ids(
            task("t1", "family-a", "common"), [], displayed_result_count=1
        )
        self.assertTrue(result["answered"])
        self.assertTrue(result["incorrect_answer"])

    def test_unmapped_result_preserves_display_rank(self):
        result = GATE.score_ids(
            task("t1", "family-a", "common"),
            [None, "good"],
            displayed_result_count=2,
        )
        self.assertFalse(result["success_at_1"])
        self.assertTrue(result["success_at_3"])

    def test_bootstrap_is_fixed_seeded_and_uses_requested_resample_count(self):
        main = [GATE.score_ids(task(f"t{i}", "f", "common"), []) for i in range(4)]
        candidate = [
            GATE.score_ids(task(f"t{i}", "f", "common"), ["good"])
            for i in range(4)
        ]
        first = GATE.paired_bootstrap(main, candidate, seed=7, resamples=100)
        second = GATE.paired_bootstrap(main, candidate, seed=7, resamples=100)
        self.assertEqual(first, second)
        self.assertEqual(first["resamples"], 100)
        self.assertEqual(first["observed_success_at_1_gain"], 1.0)
        self.assertEqual(first["one_sided_95_lower_bound"], 1.0)
        self.assertFalse(first["interval_contains_zero"])

    def test_gate_rejects_family_safety_and_inconclusive_bootstrap_regressions(self):
        tasks = [
            task("a1", "family-a", "common"),
            task("a2", "family-a", "common"),
            task("b1", "family-b", "linux"),
            task("u1", "family-b", "linux", answerable=False),
        ]
        main = [GATE.score_ids(item, []) for item in tasks]
        candidate = [
            GATE.score_ids(tasks[0], ["good"]),
            GATE.score_ids(tasks[1], ["wrong"]),
            GATE.score_ids(tasks[2], []),
            GATE.score_ids(tasks[3], ["wrong"]),
        ]
        quality = GATE.compare_quality(tasks, main, candidate)
        bootstrap = GATE.paired_bootstrap(main, candidate, resamples=100)
        performance = {
            "main": {"warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100}},
            "candidate": {"warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100}},
        }
        gate = GATE.evaluate_gate(quality, bootstrap, performance)
        self.assertFalse(gate["passed"])
        self.assertIn("fewer than two scenario families improved in Success@1", gate["reasons"])
        self.assertIn(
            "one-sided paired bootstrap lower bound is not above zero", gate["reasons"]
        )
        self.assertTrue(any("false_answers" in reason for reason in gate["reasons"]))

    def test_gate_passes_with_crossing_interval_and_positive_one_sided_bound(self):
        tasks = [
            *[task(f"a-positive-{i}", "family-a", "common") for i in range(10)],
            *[task(f"a-negative-{i}", "family-a", "common") for i in range(6)],
            *[task(f"b-positive-{i}", "family-b", "common") for i in range(10)],
            *[task(f"b-negative-{i}", "family-b", "common") for i in range(5)],
        ]
        improvements = [True] * 10 + [False] * 6 + [True] * 10 + [False] * 5
        main = []
        candidate = []
        for item, improved in zip(tasks, improvements):
            if improved:
                main.append(GATE.score_ids(item, []))
                candidate.append(GATE.score_ids(item, ["good"]))
            else:
                main.append(GATE.score_ids(item, ["good"]))
                candidate.append(GATE.score_ids(item, ["wrong", "good"]))
        quality = GATE.compare_quality(tasks, main, candidate)
        performance = {
            "main": {"warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100}},
            "candidate": {"warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100}},
        }
        bootstrap = GATE.paired_bootstrap(main, candidate, seed=7, resamples=10_000)

        self.assertLess(bootstrap["interval_95"]["lower"], 0)
        self.assertGreater(bootstrap["interval_95"]["upper"], 0)
        self.assertTrue(bootstrap["interval_contains_zero"])
        self.assertGreater(bootstrap["one_sided_95_lower_bound"], 0)

        gate = GATE.evaluate_gate(quality, bootstrap, performance)

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["reasons"], [])

    def test_nonpositive_one_sided_bound_fails_the_gate(self):
        tasks = [task(f"a{i}", "family-a", "common") for i in range(5)] + [
            task(f"b{i}", "family-b", "linux") for i in range(5)
        ]
        main = [GATE.score_ids(item, []) for item in tasks]
        candidate = [
            GATE.score_ids(item, ["good"] if index in (0, 5) else [])
            for index, item in enumerate(tasks)
        ]
        quality = GATE.compare_quality(tasks, main, candidate)
        performance = {
            "main": {"warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100}},
            "candidate": {"warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100}},
        }
        bootstrap = GATE.paired_bootstrap(main, candidate, seed=7, resamples=10_000)

        self.assertLessEqual(bootstrap["one_sided_95_lower_bound"], 0)

        gate = GATE.evaluate_gate(quality, bootstrap, performance)

        self.assertFalse(gate["passed"])
        self.assertIn(
            "one-sided paired bootstrap lower bound is not above zero", gate["reasons"]
        )

    def test_performance_gate_rejects_missing_or_over_budget_measurements(self):
        passed, reasons = GATE.performance_gate(
            {
                "main": {"warmed_query": {"p95_ms": 10, "peak_memory_bytes": None}},
                "candidate": {"warmed_query": {"p95_ms": 13, "peak_memory_bytes": 120}},
            }
        )
        self.assertFalse(passed)
        self.assertIn("warmed-query peak_memory_bytes is unavailable", reasons)
        self.assertIn("warmed-query p95_ms regressed by more than 20%", reasons)

    def test_execution_failures_make_gate_inconclusive(self):
        tasks = [task("t1", "family-a", "common")]
        main = [GATE.score_ids(tasks[0], ["good"])]
        candidate = [GATE.score_ids(tasks[0], ["good"])]
        quality = GATE.compare_quality(tasks, main, candidate)
        bootstrap = GATE.paired_bootstrap(main, candidate, resamples=100)
        performance = {
            "main": {"warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100}},
            "candidate": {"warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100}},
        }
        gate = GATE.evaluate_gate(
            quality,
            bootstrap,
            performance,
            {"main": [], "candidate": [{"task_id": "t1", "exit_status": 1}]},
        )
        self.assertFalse(gate["passed"])
        self.assertIn("CLI execution failures: candidate=1", gate["reasons"])


if __name__ == "__main__":
    unittest.main()
