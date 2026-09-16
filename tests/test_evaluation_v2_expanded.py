import json
import importlib.util
import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json"
DEV_PATH = ROOT / "tests/fixtures/evaluation/frozen-dev-v2-expanded.json"
HOLDOUT_PATH = ROOT / "tests/fixtures/evaluation/frozen-holdout-v2-expanded.json"
CORPUS_PATH = ROOT / "tests/fixtures/tldr-evaluation-v2/manifest.json"
INTENTS_PATH = ROOT / "tests/fixtures/evaluation/task-intents-v2-expanded.json"
CATALOG_PATH = ROOT / "tests/fixtures/evaluation/evaluation-v2-support-catalog-expanded.json"
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
        self.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    def test_versioned_expanded_freeze_validates(self):
        VALIDATOR.validate_manifest(MANIFEST_PATH)
        self.assertEqual(self.manifest["freeze_id"], "evaluation-v2-release-benchmark-v3")
        self.assertEqual(
            self.manifest["previous_freeze_id"], "evaluation-v2-release-benchmark-v2"
        )
        self.assertEqual(self.development["freeze_id"], self.manifest["freeze_id"])
        self.assertEqual(self.holdout["freeze_id"], self.manifest["freeze_id"])

    def test_dataset_freeze_identity_must_match_manifest(self):
        mutated = copy.deepcopy(self.development)
        mutated["freeze_id"] = "evaluation-v2-release-benchmark-v2"
        with self.assertRaisesRegex(ValueError, "freeze ID mismatch"):
            VALIDATOR.validate_dataset_freeze_id(self.manifest, mutated, "dev")

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
        VALIDATOR.validate_split_question_disjointness(
            self.development, self.holdout
        )
        VALIDATOR.validate_family_intents(
            self.intents, self.development, self.holdout
        )
        VALIDATOR.validate_support_catalog(
            self.catalog,
            self.manifest,
            self.corpus,
            self.development,
            self.holdout,
        )
        VALIDATOR.validate_support_audit(
            self.manifest["support_audit"],
            self.development,
            self.holdout,
            self.intents,
            self.catalog,
        )
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

    def test_family_intent_validation_rejects_mixed_family(self):
        mutated = copy.deepcopy(self.intents)
        family_records = [
            task
            for task in mutated["tasks"]
            if task["family"] == "dev39-common-file-content"
        ]
        family_records[-1]["intent"] = "a different behavior"
        with self.assertRaisesRegex(ValueError, "one exact"):
            VALIDATOR.validate_family_intents(
                mutated, self.development, self.holdout
            )

    def test_support_audit_rejects_unrelated_example(self):
        mutated = copy.deepcopy(self.development)
        mutated_audit = copy.deepcopy(self.manifest["support_audit"])
        task_id = mutated["tasks"][0]["id"]
        mutated["tasks"][0]["acceptable_example_ids"] = [
            "example-d0e3fda8bc712264a0e01e7c181e34b302bb2e5052228147e97b1d9ee79405f8"
        ]
        mutated_audit["tasks"][task_id]["acceptable_example_ids"] = mutated["tasks"][0][
            "acceptable_example_ids"
        ]
        with self.assertRaisesRegex(ValueError, "support catalog behavior"):
            VALIDATOR.validate_support_audit(
                mutated_audit,
                mutated,
                self.holdout,
                self.intents,
                self.catalog,
            )

    def test_support_catalog_rejects_unlinked_source_section(self):
        mutated = copy.deepcopy(self.catalog)
        example_id = (
            "example-b1339e30586a6a791eb124959561905d0f2c467a62a74a4faa6e2cee104a8651"
        )
        mutated["entries"][example_id]["section"] = (
            "Concatenate several files into an output file:"
        )
        with self.assertRaisesRegex(ValueError, "source section"):
            VALIDATOR.validate_support_catalog(
                mutated,
                self.manifest,
                self.corpus,
                self.development,
                self.holdout,
            )

    def test_split_question_validation_rejects_normalized_leakage(self):
        mutated = copy.deepcopy(self.holdout)
        mutated["tasks"][0]["question"] = (
            "  Configure a Linux firewall rule with nftables!!! "
        )
        with self.assertRaisesRegex(ValueError, "questions overlap after normalization"):
            VALIDATOR.validate_split_question_disjointness(
                self.development, mutated
            )

    def test_holdout_append_task_uses_append_example(self):
        task = next(
            task
            for task in self.holdout["tasks"]
            if "append" in task["question"].lower()
        )
        append_example_id = (
            "example-960cbf5056bae848f6fa5828c3c9dd960b95dff60228d904620f77c3d0b47f69"
        )
        self.assertEqual(task["acceptable_example_ids"], [append_example_id])
        self.assertIn(">>", task["rationale"])
        self.assertEqual(
            self.manifest["support_audit"]["tasks"][task["id"]][
                "acceptable_example_ids"
            ],
            [append_example_id],
        )

    def test_speech_tasks_include_all_compatible_say_examples(self):
        speech_intent = "speak a phrase aloud with macOS say"
        expected_compatible_ids = {
            "example-aa4471a722c72a121cbd4edb616ea9725e4541d1303864a8f74fc7a3a60222cf",
            "example-b81c48d57981c4099a14be07cda1740b1ea1ab1e3a78c67694ebf3e2bfc9fd24",
            "example-ec44c763687e9e1158242b809efff5730f320a7cfa1a884737b8f6e38676f54d",
        }
        catalog_compatible_ids = {
            example_id
            for example_id, entry in self.catalog["entries"].items()
            if entry["source_path"] == "pages/osx/say.md"
            and entry["canonical_behavior"] == speech_intent
        }
        self.assertEqual(catalog_compatible_ids, expected_compatible_ids)
        speech_tasks = [
            task
            for task in self.holdout["tasks"]
            if task["family"] == "holdout39-osx-speech-phrase"
        ]
        self.assertEqual(len(speech_tasks), 5)
        for task in speech_tasks:
            self.assertEqual(set(task["acceptable_example_ids"]), expected_compatible_ids)
            self.assertEqual(
                set(
                    self.manifest["support_audit"]["tasks"][task["id"]][
                        "acceptable_example_ids"
                    ]
                ),
                expected_compatible_ids,
            )

    def test_hand_checks_reject_mutated_support_citation(self):
        mutated = copy.deepcopy(self.manifest["hand_checks"])
        mutated[0]["evidence"]["acceptable_support"]["citations"] = [
            {
                "catalog_entry_id": mutated[0]["evidence"]["acceptable_support"][
                    "observed_example_ids"
                ][0],
                "source_path": "pages/common/cat.md",
                "source_line": 999,
                "section": "Print the contents of a file to `stdout`: ",
                "source_digest": self.manifest["corpus"]["source_digest"],
            }
        ]
        with self.assertRaisesRegex(ValueError, "citation"):
            VALIDATOR.validate_hand_checks(
                mutated,
                self.manifest["hand_check_provenance"],
                self.development,
                self.holdout,
                self.intents,
                self.catalog,
                self.manifest["support_catalog"],
                self.manifest["corpus"],
            )

    def test_hand_checks_reject_unsupported_citation_id(self):
        mutated = copy.deepcopy(self.manifest["hand_checks"])
        mutated[0]["evidence"]["behavior"]["citations"] = [
            {
                "catalog_entry_id": "example-" + "0" * 64,
                "source_path": "pages/common/cat.md",
                "source_line": 8,
                "section": "Print the contents of a file to `stdout`: ",
                "source_digest": self.manifest["corpus"]["source_digest"],
            }
        ]
        with self.assertRaisesRegex(ValueError, "citation"):
            VALIDATOR.validate_hand_checks(
                mutated,
                self.manifest["hand_check_provenance"],
                self.development,
                self.holdout,
                self.intents,
                self.catalog,
                self.manifest["support_catalog"],
                self.manifest["corpus"],
            )

    def test_hand_checks_reject_false_abstention_scan(self):
        mutated = copy.deepcopy(self.manifest["hand_checks"])
        record = next(
            record
            for record in mutated
            if not next(
                task
                for task in self.development["tasks"] + self.holdout["tasks"]
                if task["id"] == record["task_id"]
            )["answerable"]
        )
        record["evidence"]["behavior"]["no_match_scan"]["matching_example_ids"] = [
            next(iter(self.catalog["entries"]))
        ]
        with self.assertRaisesRegex(ValueError, "no-match scan"):
            VALIDATOR.validate_hand_checks(
                mutated,
                self.manifest["hand_check_provenance"],
                self.development,
                self.holdout,
                self.intents,
                self.catalog,
                self.manifest["support_catalog"],
                self.manifest["corpus"],
            )

    def test_hand_checks_reject_stale_no_match_scan(self):
        mutated = copy.deepcopy(self.manifest["hand_checks"])
        record = next(
            record
            for record in mutated
            if not next(
                task
                for task in self.development["tasks"] + self.holdout["tasks"]
                if task["id"] == record["task_id"]
            )["answerable"]
        )
        record["evidence"]["acceptable_support"]["no_match_scan"][
            "catalog_sha256"
        ] = "0" * 64
        with self.assertRaisesRegex(ValueError, "no-match scan"):
            VALIDATOR.validate_hand_checks(
                mutated,
                self.manifest["hand_check_provenance"],
                self.development,
                self.holdout,
                self.intents,
                self.catalog,
                self.manifest["support_catalog"],
                self.manifest["corpus"],
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
        VALIDATOR.validate_hand_checks(
            self.manifest["hand_checks"],
            self.manifest["hand_check_provenance"],
            self.development,
            self.holdout,
            self.intents,
            self.catalog,
            self.manifest["support_catalog"],
            self.manifest["corpus"],
        )
        self.assertEqual(
            len(self.manifest["hand_checks"]),
            len({task["family"] for task in self.development["tasks"] + self.holdout["tasks"]}),
        )

    def test_hand_checks_reject_inconsistent_platform_evidence(self):
        mutated = copy.deepcopy(self.manifest["hand_checks"])
        mutated[0]["evidence"]["platform"]["observed_platform"] = "linux"
        with self.assertRaisesRegex(ValueError, "hand-check platform"):
            VALIDATOR.validate_hand_checks(
                mutated,
                self.manifest["hand_check_provenance"],
                self.development,
                self.holdout,
                self.intents,
                self.catalog,
                self.manifest["support_catalog"],
                self.manifest["corpus"],
            )

    def test_published_reports_pin_all_release_digests(self):
        for split, report_path in REPORT_PATHS.items():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            dataset_path = DEV_PATH if split == "dev" else HOLDOUT_PATH
            self.assertEqual(report["freeze_id"], self.manifest["freeze_id"])
            self.assertEqual(
                report["dataset_sha256"], VALIDATOR.RUNNER.sha256_file(dataset_path)
            )
            self.assertEqual(report["support_catalog"], self.manifest["support_catalog"])
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
