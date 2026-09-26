import importlib.util
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


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


def matching_main_and_candidate_inputs(root):
    main_data_dir = root / "main-data"
    model_relative = Path(
        "models--Qdrant--all-MiniLM-L6-v2-onnx/refs/main"
    )
    model_content = b"5f1b8cd78bc4fb444dd171e59b18f3a3af89a079\n"
    main_model = main_data_dir / "models" / model_relative
    main_model.parent.mkdir(parents=True)
    main_model.write_bytes(model_content)

    main_database = main_data_dir / "commands.db"
    with closing(sqlite3.connect(main_database)) as connection, connection:
        connection.execute(
            "CREATE TABLE pages_vec "
            "(os TEXT, command TEXT, description TEXT, example_desc TEXT, example_cmd TEXT, embedding BLOB)"
        )
        connection.execute(
            "INSERT INTO pages_vec VALUES (?, ?, ?, ?, ?, ?)",
            ("common", "ls", "List directory contents.", "List files.", "ls -1", b"\x00"),
        )

    bundle = root / "bundle"
    bundle.mkdir()
    candidate_model = bundle / "model-cache" / model_relative
    candidate_model.parent.mkdir(parents=True)
    candidate_model.write_bytes(model_content)
    model_digest = hashlib.sha256(model_content).hexdigest()
    bundle_manifest = {
        "bundle_id": "test-bundle",
        "parser_version": "tldr-subset-v4",
        "source": {"revision": "a" * 40, "digest": "c" * 64},
        "embedding_model": {
            "assets": [
                {
                    "path": f"model-cache/{model_relative.as_posix()}",
                    "size_bytes": len(model_content),
                    "sha256": model_digest,
                }
            ]
        },
    }
    (bundle / "manifest.json").write_text(
        json.dumps(bundle_manifest) + "\n", encoding="utf-8"
    )
    with closing(sqlite3.connect(bundle / "matching.db")) as connection, connection:
        connection.execute(
            "CREATE TABLE pages "
            "(page_id TEXT, platform TEXT, command TEXT, description TEXT)"
        )
        connection.execute(
            "CREATE TABLE examples "
            "(example_id TEXT, page_id TEXT, description TEXT, command TEXT)"
        )
        connection.execute(
            "INSERT INTO pages VALUES (?, ?, ?, ?)",
            ("page-1", "common", "ls", "List directory contents."),
        )
        connection.execute(
            "INSERT INTO examples VALUES (?, ?, ?, ?)",
            ("example-1", "page-1", "List files.", "ls -1"),
        )
    return main_data_dir, bundle


def pin_synthetic_main_database_digest(main_data_dir):
    real_sha256_file = GATE.sha256_file
    main_database = (main_data_dir / "commands.db").resolve()

    def sha256_file(path):
        if Path(path).resolve() == main_database:
            return GATE.PINNED_MAIN_DATABASE_SHA256
        return real_sha256_file(Path(path))

    return mock.patch.object(GATE, "sha256_file", side_effect=sha256_file)


class ReleaseGateTests(unittest.TestCase):
    def test_static_macos_binary_does_not_require_an_ort_rpath(self):
        static_binary_dependencies = (
            "askman:\n"
            "\t/usr/lib/libc++.1.dylib\n"
            "\t/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation\n"
        )
        with (
            mock.patch.object(GATE.platform, "system", return_value="Darwin"),
            mock.patch.object(
                GATE.subprocess,
                "run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=static_binary_dependencies,
                    stderr="",
                ),
            ),
            mock.patch.dict(GATE.os.environ, {}, clear=True),
        ):
            self.assertIsNone(GATE.bake_ort_rpath(Path("askman")))

    def test_release_gate_builds_with_the_static_pinned_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "candidate-source"
            binary = root / "candidate-target" / "release" / "askman"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"test binary")
            cargo_environments = []

            def fake_run_command(command, *, cwd=None):
                Path(command[6]).mkdir(parents=True)
                (Path(command[6]) / "Cargo.lock").write_text("test lock\n")
                return ""

            def fake_subprocess_run(command, **kwargs):
                if command[0] == "cargo":
                    cargo_environments.append(kwargs["env"])
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                if command[0] == "otool":
                    return SimpleNamespace(
                        returncode=0,
                        stdout=(
                            "askman:\n"
                            "\t/usr/lib/libc++.1.dylib\n"
                            "\t/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation\n"
                        ),
                        stderr="",
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                mock.patch.object(GATE.platform, "system", return_value="Darwin"),
                mock.patch.object(GATE, "run_command", side_effect=fake_run_command),
                mock.patch.object(GATE, "git_revision", return_value="candidate-commit"),
                mock.patch.object(GATE.subprocess, "run", side_effect=fake_subprocess_run),
                mock.patch.dict(GATE.os.environ, {}, clear=True),
            ):
                report = GATE.build_binary(ROOT, "HEAD", "candidate", root)

        self.assertEqual(report["ort_rpath"], None)
        self.assertEqual(len(cargo_environments), 1)
        self.assertEqual(
            cargo_environments[0]["ORT_PREFER_DYNAMIC_LINK"], "0"
        )
        self.assertEqual(
            cargo_environments[0]["LIBONNXRUNTIME_NO_PKG_CONFIG"], "1"
        )

    def test_main_data_inputs_match_candidate_visible_corpus_and_model(self):
        with tempfile.TemporaryDirectory() as directory:
            main_data_dir, bundle = matching_main_and_candidate_inputs(Path(directory))
            parity = {
                "visible_corpus_example_count": 1,
                "visible_corpus_examples_sha256": hashlib.sha256(
                    json.dumps(
                        [["common", "ls", "List directory contents.", "List files.", "ls -1"]],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
            with (
                pin_synthetic_main_database_digest(main_data_dir),
                mock.patch.object(
                    GATE, "run_command", return_value=json.dumps(parity)
                ) as run_command,
            ):
                compatibility = GATE.validate_main_data_compatibility(
                    main_data_dir, bundle
                )
        self.assertEqual(
            compatibility["visible_corpus_examples_sha256"],
            parity["visible_corpus_examples_sha256"],
        )
        self.assertEqual(compatibility["model_asset_count"], 1)
        self.assertTrue(compatibility["model_assets_match"])
        self.assertEqual(compatibility["candidate_source_digest"], "c" * 64)
        self.assertEqual(compatibility["candidate_parser_version"], "tldr-subset-v4")
        self.assertEqual(compatibility["candidate_source_revision"], "a" * 40)
        self.assertTrue(compatibility["main_database_matches_pinned_baseline"])
        self.assertEqual(
            compatibility["main_database_sha256"],
            GATE.PINNED_MAIN_DATABASE_SHA256,
        )
        self.assertEqual(
            compatibility["model_asset_digests"],
            {
                "models--Qdrant--all-MiniLM-L6-v2-onnx/refs/main": hashlib.sha256(
                    b"5f1b8cd78bc4fb444dd171e59b18f3a3af89a079\n"
                ).hexdigest()
            },
        )
        self.assertIn("compare-visible-corpus", run_command.call_args.args[0])

    def test_benchmark_corpus_must_match_candidate_bundle(self):
        candidate_corpus = {
            "parser_version": "tldr-subset-v4",
            "source_revision": "a" * 40,
            "source_digest": "c" * 64,
        }
        dataset = {
            "corpus": {
                "corpus_id": f"{'a' * 40}:{'c' * 64}",
                **candidate_corpus,
            }
        }

        identity = GATE.validate_benchmark_corpus_compatibility(
            dataset, candidate_corpus, "dev"
        )

        self.assertEqual(identity["source_digest"], "c" * 64)
        dataset["corpus"]["corpus_id"] = f"tldr-pages@{'a' * 40}"
        with self.assertRaisesRegex(
            ValueError, "dev benchmark corpus ID is inconsistent"
        ):
            GATE.validate_benchmark_corpus_compatibility(
                dataset, candidate_corpus, "dev"
            )
        identity = GATE.validate_benchmark_corpus_compatibility(
            dataset,
            candidate_corpus,
            "holdout",
            allow_legacy_tldr_corpus_id=True,
        )
        self.assertEqual(identity["source_revision"], "a" * 40)

        dataset["corpus"]["source_digest"] = "d" * 64
        dataset["corpus"]["corpus_id"] = f"{'a' * 40}:{'d' * 64}"
        with self.assertRaisesRegex(
            ValueError, "dev benchmark corpus mismatch for source_digest"
        ):
            GATE.validate_benchmark_corpus_compatibility(
                dataset, candidate_corpus, "dev"
            )

    def test_parser_mismatch_requires_exact_record_equivalence(self):
        dataset = {
            "corpus": {
                "corpus_id": f"{'a' * 40}:{'c' * 64}",
                "parser_version": "tldr-subset-v3",
                "source_revision": "a" * 40,
                "source_digest": "c" * 64,
            }
        }
        candidate_corpus = {
            **dataset["corpus"],
            "parser_version": "tldr-subset-v4",
        }

        with self.assertRaisesRegex(ValueError, "exact record-equivalence"):
            GATE.validate_benchmark_corpus_compatibility(
                dataset, candidate_corpus, "dev"
            )

        proof = {
            "records_identical": True,
            "reference_parser_version": "tldr-subset-v3",
            "candidate_parser_version": "tldr-subset-v4",
        }
        compatibility = GATE.validate_benchmark_corpus_compatibility(
            dataset, candidate_corpus, "dev", proof
        )
        self.assertEqual(
            compatibility["parser_compatibility"], "exact-record-equivalence"
        )

    def test_gate_rejects_benchmark_corpus_mismatch_before_building_binaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main_data_dir, bundle = matching_main_and_candidate_inputs(root)
            arguments = [
                "--dev-only",
                "--main-data-dir",
                str(main_data_dir),
                "--bundle",
                str(bundle),
                "--output-json",
                str(root / "report.json"),
                "--output-markdown",
                str(root / "report.md"),
                "--warmup-queries",
                "1",
                "--warm-queries",
                "1",
            ]
            candidate_identity = {
                "candidate_parser_version": "tldr-subset-v4",
                "candidate_source_revision": "a" * 40,
                "candidate_source_digest": "c" * 64,
            }

            with (
                mock.patch.object(
                    GATE, "validate_main_data_compatibility", return_value=candidate_identity
                ),
                mock.patch.object(GATE, "build_binary") as build_binary,
            ):
                self.assertEqual(GATE.main(arguments), 2)

            build_binary.assert_not_called()

    def test_unpinned_main_database_is_rejected_for_release_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            main_data_dir, bundle = matching_main_and_candidate_inputs(Path(directory))

            with self.assertRaisesRegex(ValueError, "does not match the pinned evaluation baseline"):
                GATE.validate_main_data_compatibility(main_data_dir, bundle)

    def test_custom_dev_dataset_requires_dev_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arguments = GATE.parser().parse_args(
                [
                    "--allow-custom-dev-dataset",
                    "--main-data-dir",
                    str(root / "main-data"),
                    "--bundle",
                    str(root / "bundle"),
                    "--output-json",
                    str(root / "report.json"),
                    "--output-markdown",
                    str(root / "report.md"),
                ]
            )

            with self.assertRaisesRegex(ValueError, "requires --dev-only"):
                GATE.run(arguments)

    def test_custom_dev_dataset_requires_schema_3_and_valid_labels_shape(self):
        freeze_path = ROOT / "tests/fixtures/evaluation/dev-only-extension-v1.manifest.json"
        freeze, dataset_path = GATE.validate_custom_dev_freeze(
            freeze_path, None, ROOT
        )
        self.assertEqual(
            dataset_path,
            (ROOT / "tests/fixtures/evaluation/dev-only-extension-v1.json").resolve(),
        )
        dataset = GATE.load_json(
            dataset_path
        )
        GATE.validate_custom_dev_dataset(dataset, freeze)

        changed = dict(dataset)
        changed["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "must use schema 3"):
            GATE.validate_custom_dev_dataset(changed, freeze)

    def test_custom_dev_dataset_skips_only_its_frozen_v2_digest(self):
        manifest = ROOT / "tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json"
        dataset = ROOT / "tests/fixtures/evaluation/dev-only-extension-v1.json"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            GATE.validate_frozen_inputs(manifest, dataset)

        GATE.validate_frozen_inputs(
            manifest, dataset, allow_custom_dev_dataset=True
        )

    def test_vector_only_main_database_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            main_data_dir, bundle = matching_main_and_candidate_inputs(Path(directory))
            database = main_data_dir / "commands.db"
            pinned_digest = GATE.sha256_file(database)
            parity = {
                "visible_corpus_example_count": 1,
                "visible_corpus_examples_sha256": "d" * 64,
            }
            with (
                mock.patch.object(GATE, "PINNED_MAIN_DATABASE_SHA256", pinned_digest),
                mock.patch.object(GATE, "run_command", return_value=json.dumps(parity)),
            ):
                GATE.validate_main_data_compatibility(main_data_dir, bundle)

                with closing(sqlite3.connect(database)) as connection, connection:
                    connection.execute(
                        "UPDATE pages_vec SET embedding = ?", (b"\x01",)
                    )

                with self.assertRaisesRegex(ValueError, "does not match the pinned evaluation baseline"):
                    GATE.validate_main_data_compatibility(main_data_dir, bundle)

    def test_main_data_comparison_failure_blocks_the_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            main_data_dir, bundle = matching_main_and_candidate_inputs(Path(directory))
            with (
                pin_synthetic_main_database_digest(main_data_dir),
                mock.patch.object(
                    GATE,
                    "run_command",
                    side_effect=RuntimeError("visible example inventory differ"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "visible example inventory"):
                    GATE.validate_main_data_compatibility(main_data_dir, bundle)

    def test_main_data_with_different_model_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            main_data_dir, bundle = matching_main_and_candidate_inputs(Path(directory))
            model = next((main_data_dir / "models").rglob("main"))
            model.write_bytes(b"different revision\n")

            with pin_synthetic_main_database_digest(main_data_dir):
                with self.assertRaisesRegex(ValueError, "model asset mismatch"):
                    GATE.validate_main_data_compatibility(main_data_dir, bundle)

    def test_dev_only_does_not_touch_holdout_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main_data_dir, bundle = matching_main_and_candidate_inputs(root)
            dev_dataset = GATE.load_json(
                ROOT / "tests/fixtures/evaluation/frozen-dev-v2-expanded.json"
            )
            manifest_path = bundle / "manifest.json"
            bundle_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            bundle_manifest["parser_version"] = dev_dataset["corpus"]["parser_version"]
            bundle_manifest["source"]["revision"] = dev_dataset["corpus"]["source_revision"]
            bundle_manifest["source"]["digest"] = dev_dataset["corpus"]["source_digest"]
            manifest_path.write_text(json.dumps(bundle_manifest), encoding="utf-8")

            holdout = (root / "guarded-holdout.json").resolve()
            arguments = [
                "--dev-only",
                "--main-data-dir",
                str(main_data_dir),
                "--bundle",
                str(bundle),
                "--holdout-dataset",
                str(holdout),
                "--output-json",
                str(root / "report.json"),
                "--output-markdown",
                str(root / "report.md"),
                "--warmup-queries",
                "1",
                "--warm-queries",
                "1",
            ]

            def fake_build_binary(repo, ref, label, scratch, *, working_tree=False):
                return {
                    "ref": "working-tree" if working_tree else ref,
                    "commit": f"{label}-commit",
                    "cargo_lock_sha256": f"{label}-lock",
                    "binary_sha256": f"{label}-binary",
                    "binary_bytes": 1,
                    "binary": str(root / f"{label}-askman"),
                    "ort_rpath": None,
                    "build_elapsed_ms": 1.0,
                    "command": [],
                }

            def fake_run_tasks(binary, data_dir, tasks, *prefixes, **kwargs):
                candidate_binary = Path(binary).name.startswith("candidate")
                outcomes = [
                    GATE.score_ids(
                        item,
                        [(example_id,) for example_id in item["acceptable_example_ids"]]
                        if candidate_binary and item["answerable"]
                        else [],
                    )
                    for item in tasks
                ]
                runs = [
                    SimpleNamespace(
                        exit_status=0,
                        timed_out=False,
                        stderr="",
                        elapsed_ms=1.0,
                        peak_memory_bytes=1,
                    )
                    for _ in tasks
                ]
                return outcomes, runs

            def fake_warm_latency(*args, **kwargs):
                return {
                    "p50_ms": 1.0,
                    "p95_ms": 1.0,
                    "peak_memory_bytes": 1,
                    "sample_count": 1,
                    "memory_sample_count": 1,
                    "warmup_queries": 1,
                    "measured_queries": 1,
                    "process_scope": "test",
                    "execution_failures": [],
                }

            def fake_run_command(command, *, cwd=None):
                if "compare-visible-corpus" in command:
                    return json.dumps(
                        {
                            "visible_corpus_example_count": 1,
                            "visible_corpus_examples_sha256": "d" * 64,
                        }
                    )
                return "test version"

            real_is_file = Path.is_file

            def reject_holdout_access(path):
                if path == holdout:
                    raise AssertionError("dev-only touched holdout path")
                return real_is_file(path)

            with (
                mock.patch.object(GATE, "build_binary", side_effect=fake_build_binary),
                mock.patch.object(GATE, "run_tasks", side_effect=fake_run_tasks),
                mock.patch.object(GATE, "run_command", side_effect=fake_run_command),
                mock.patch.object(GATE, "warm_latency", side_effect=fake_warm_latency),
                mock.patch.object(GATE, "network_wrapper", return_value=([], "test")),
                mock.patch.object(GATE, "time_wrapper", return_value=([], "test")),
                mock.patch.object(Path, "is_file", new=reject_holdout_access),
            ):
                self.assertEqual(GATE.main(arguments), 0)

            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            markdown = (root / "report.md").read_text(encoding="utf-8")
            self.assertEqual(report["schema_version"], 4)
            self.assertEqual(
                report["inputs"]["gate_runner_sha256"],
                GATE.sha256_file(ROOT / "scripts/run_release_gate.py"),
            )
            self.assertEqual(report["gate"]["decision"], "inconclusive")
            self.assertEqual(report["recommendation"], "inconclusive")
            self.assertFalse(report["protocol"]["development_and_holdout"])
            self.assertTrue(report["inputs"]["input_compatibility"]["model_assets_match"])
            self.assertTrue(
                report["inputs"]["benchmark_corpus_compatibility"][
                    "dev"
                ][
                    "matches_candidate_bundle"
                ]
            )
            self.assertFalse(
                report["inputs"]["input_compatibility"][
                    "main_database_matches_pinned_baseline"
                ]
            )
            self.assertIn("One-sided 95% lower bound", markdown)
            self.assertIn(report["inputs"]["gate_runner_sha256"], markdown)
            self.assertIn(
                "dev-only evidence cannot make a release decision",
                report["gate"]["reasons"],
            )

    def test_parser_maps_user_visible_example_pairs(self):
        output = """
        \x1b[32mls\x1b[0m
        List directory contents.

        \x1b[4mExamples:\x1b[0m
          List one per line.
           ls -1
        """
        self.assertEqual(
            GATE.parse_displayed_results(output),
            [
                {
                    "page_command": "ls",
                    "page_description": "List directory contents.",
                    "description": "List one per line.",
                    "command": "ls -1",
                }
            ],
        )

    def test_parser_captures_visible_page_identity(self):
        output = """
        \x1b[32mzip\x1b[0m
        Create a ZIP archive.
        See also: `unzip`.
        More information: <https://example.com/zip>.

        Examples:
          Compress one file.
           zip archive.zip input.txt
        """

        self.assertEqual(
            GATE.parse_displayed_results(output),
            [
                {
                    "page_command": "zip",
                    "page_description": "Create a ZIP archive.\nSee also: `unzip`.",
                    "description": "Compress one file.",
                    "command": "zip archive.zip input.txt",
                }
            ],
        )

    def test_parser_keeps_all_examples_in_one_block(self):
        output = """
        ls
        List directory contents.

        Examples:
          List one per line.
           ls -1

          List all entries.
           ls -a
        """
        self.assertEqual(
            GATE.parse_displayed_results(output),
            [
                {
                    "page_command": "ls",
                    "page_description": "List directory contents.",
                    "description": "List one per line.",
                    "command": "ls -1",
                },
                {
                    "page_command": "ls",
                    "page_description": "List directory contents.",
                    "description": "List all entries.",
                    "command": "ls -a",
                },
            ],
        )

    def test_example_index_preserves_platforms_for_identical_visible_examples(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            with closing(sqlite3.connect(bundle / "matching.db")) as connection, connection:
                connection.execute(
                    "CREATE TABLE pages "
                    "(page_id TEXT, platform TEXT, command TEXT, description TEXT)"
                )
                connection.execute(
                    "CREATE TABLE examples "
                    "(example_id TEXT, page_id TEXT, description TEXT, command TEXT)"
                )
                connection.executemany(
                    "INSERT INTO pages VALUES (?, ?, ?, ?)",
                    [
                        ("common-page", "common", "tool", "Tool page."),
                        ("osx-page", "osx", "tool", "Tool page."),
                        ("linux-page", "linux", "tool", "Tool page."),
                    ],
                )
                connection.executemany(
                    "INSERT INTO examples VALUES (?, ?, ?, ?)",
                    [
                        ("common-id", "common-page", "Same visible result.", "command --arg"),
                        ("osx-id", "osx-page", "Same visible result.", "command --arg"),
                        ("linux-id", "linux-page", "Same visible result.", "command --arg"),
                    ],
                )

            key = (
                GATE.normalize_command_text("tool"),
                GATE.normalize_description_text("Tool page."),
                GATE.normalize_description_text("Same visible result."),
                GATE.normalize_command_text("command --arg"),
            )
            self.assertEqual(
                GATE.example_index(bundle)[key],
                {
                    "common": ("common-id",),
                    "osx": ("osx-id",),
                    "linux": ("linux-id",),
                },
            )

    def test_output_mapping_matches_flattened_multiline_descriptions(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            with closing(sqlite3.connect(bundle / "matching.db")) as connection, connection:
                connection.execute(
                    "CREATE TABLE pages "
                    "(page_id TEXT, platform TEXT, command TEXT, description TEXT)"
                )
                connection.execute(
                    "CREATE TABLE examples "
                    "(example_id TEXT, page_id TEXT, description TEXT, command TEXT)"
                )
                connection.execute(
                    "INSERT INTO pages VALUES (?, ?, ?, ?)",
                    (
                        "copy-page",
                        "windows",
                        "copy",
                        "Copy files\nfrom one location to another.",
                    ),
                )
                connection.execute(
                    "INSERT INTO examples VALUES (?, ?, ?, ?)",
                    (
                        "copy-example",
                        "copy-page",
                        "Copy\none file to another location.",
                        "copy source.txt target.txt",
                    ),
                )

            output = """
            copy
            Copy files from one location to another.

            Examples:
              Copy one file to another location.
               copy source.txt target.txt
            """

            displayed_ids, unmapped = GATE.map_output_to_ids(
                output, GATE.example_index(bundle), "windows"
            )

            self.assertEqual(displayed_ids, (("copy-example",),))
            self.assertEqual(unmapped, ())

    def test_output_mapping_keeps_eligible_duplicate_ids_as_an_equivalence_set(self):
        output = """
        tool
        Tool page.

        Examples:
          Same visible result.
           command --arg
        """
        key = (
            GATE.normalize_command_text("tool"),
            GATE.normalize_description_text("Tool page."),
            GATE.normalize_description_text("Same visible result."),
            GATE.normalize_command_text("command --arg"),
        )
        index = {
            key: {
                "common": ("common-id",),
                "osx": ("osx-id",),
                "linux": ("linux-id",),
            }
        }

        displayed_ids, unmapped = GATE.map_output_to_ids(output, index, "osx")

        self.assertEqual(displayed_ids, (("common-id", "osx-id"),))
        self.assertEqual(unmapped, ())
        answerable_task = task("same-result", "family-a", "osx")
        answerable_task["acceptable_example_ids"] = ["osx-id"]
        scored = GATE.score_ids(answerable_task, displayed_ids)
        self.assertTrue(scored["success_at_1"])
        self.assertTrue(scored["success_at_3"])
        self.assertEqual(scored["displayed_example_ids"], [None])
        self.assertEqual(
            scored["displayed_example_id_candidates"],
            [["common-id", "osx-id"]],
        )
        out_of_scope_task = task("wrong-platform", "family-a", "osx")
        out_of_scope_task["acceptable_example_ids"] = ["linux-id"]
        self.assertFalse(GATE.score_ids(out_of_scope_task, displayed_ids)["success_at_3"])

    def test_output_mapping_does_not_credit_a_different_visible_page(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            with closing(sqlite3.connect(bundle / "matching.db")) as connection, connection:
                connection.execute(
                    "CREATE TABLE pages "
                    "(page_id TEXT, platform TEXT, command TEXT, description TEXT)"
                )
                connection.execute(
                    "CREATE TABLE examples "
                    "(example_id TEXT, page_id TEXT, description TEXT, command TEXT)"
                )
                connection.executemany(
                    "INSERT INTO pages VALUES (?, ?, ?, ?)",
                    [
                        ("tar-page", "linux", "tar", "Archive files."),
                        ("zip-page", "linux", "zip", "Create a ZIP archive."),
                    ],
                )
                connection.executemany(
                    "INSERT INTO examples VALUES (?, ?, ?, ?)",
                    [
                        ("tar-id", "tar-page", "Compress one file.", "archive input.zip input.txt"),
                        ("zip-id", "zip-page", "Compress one file.", "archive input.zip input.txt"),
                    ],
                )

            output = """
            zip
            Create a ZIP archive.

            Examples:
              Compress one file.
               archive input.zip input.txt
            """
            displayed_ids, unmapped = GATE.map_output_to_ids(
                output, GATE.example_index(bundle), "linux"
            )
            tar_task = task("tar-query", "archive", "linux")
            tar_task["acceptable_example_ids"] = ["tar-id"]
            scored = GATE.score_ids(tar_task, displayed_ids)

            self.assertEqual(displayed_ids, (("zip-id",),))
            self.assertEqual(unmapped, ())
            self.assertFalse(scored["success_at_1"])
            self.assertFalse(scored["success_at_3"])

    def test_windows_mapping_ignores_case_only_page_command_differences(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            with closing(sqlite3.connect(bundle / "matching.db")) as connection, connection:
                connection.execute(
                    "CREATE TABLE pages "
                    "(page_id TEXT, platform TEXT, command TEXT, description TEXT)"
                )
                connection.execute(
                    "CREATE TABLE examples "
                    "(example_id TEXT, page_id TEXT, description TEXT, command TEXT)"
                )
                connection.execute(
                    "INSERT INTO pages VALUES (?, ?, ?, ?)",
                    ("windows-page", "windows", "Get-ChildItem", "List directory items."),
                )
                connection.execute(
                    "INSERT INTO examples VALUES (?, ?, ?, ?)",
                    ("windows-id", "windows-page", "List non-hidden items.", "Get-ChildItem"),
                )

            output = """
            get-childitem
            List directory items.

            Examples:
              List non-hidden items.
               Get-ChildItem
            """

            displayed_ids, unmapped = GATE.map_output_to_ids(
                output, GATE.example_index(bundle), "windows"
            )

            self.assertEqual(displayed_ids, (("windows-id",),))
            self.assertEqual(unmapped, ())

    def test_common_queries_map_common_and_host_platform_results(self):
        with mock.patch.object(GATE.platform, "system", return_value="Darwin"):
            self.assertEqual(
                GATE.eligible_result_platforms("common"), {"common", "osx"}
            )

    def test_output_mapping_marks_only_out_of_scope_matches_unmapped(self):
        output = """
        tool
        Tool page.

        Examples:
          Same visible result.
           command --arg
        """
        key = (
            GATE.normalize_command_text("tool"),
            GATE.normalize_description_text("Tool page."),
            GATE.normalize_description_text("Same visible result."),
            GATE.normalize_command_text("command --arg"),
        )

        displayed_ids, unmapped = GATE.map_output_to_ids(
            output, {key: {"linux": ("linux-id",)}}, "osx"
        )

        self.assertEqual(displayed_ids, (None,))
        self.assertEqual(unmapped, tuple(GATE.parse_displayed_results(output)))

    def test_unmapped_visible_result_counts_as_an_answer(self):
        result = GATE.score_ids(
            task("t1", "family-a", "common"), [], displayed_result_count=1
        )
        self.assertTrue(result["answered"])
        self.assertTrue(result["incorrect_answer"])

    def test_unmapped_result_preserves_display_rank(self):
        result = GATE.score_ids(
            task("t1", "family-a", "common"),
            [None, ("good",)],
            displayed_result_count=2,
        )
        self.assertFalse(result["success_at_1"])
        self.assertTrue(result["success_at_3"])

    def test_bootstrap_is_fixed_seeded_and_uses_requested_resample_count(self):
        main = [GATE.score_ids(task(f"t{i}", "f", "common"), []) for i in range(4)]
        candidate = [
            GATE.score_ids(task(f"t{i}", "f", "common"), [("good",)])
            for i in range(4)
        ]
        first = GATE.paired_bootstrap(main, candidate, seed=7, resamples=100)
        second = GATE.paired_bootstrap(main, candidate, seed=7, resamples=100)
        self.assertEqual(first, second)
        self.assertEqual(first["resamples"], 100)
        self.assertEqual(first["observed_success_at_1_gain"], 1.0)
        self.assertFalse(first["interval_contains_zero"])

    def test_gate_uses_one_sided_lower_bound_not_two_sided_interval(self):
        tasks = [
            task(
                f"t{i}",
                "family-a" if i < 15 else "family-b" if i < 20 else "family-c",
                "common",
            )
            for i in range(30)
        ]
        main = [GATE.score_ids(item, []) for item in tasks]
        candidate = [
            GATE.score_ids(item, [("good",)] if index in {0, 1, 15} else [])
            for index, item in enumerate(tasks)
        ]
        bootstrap = GATE.paired_bootstrap(main, candidate, seed=7, resamples=10_000)
        self.assertTrue(bootstrap["interval_contains_zero"])
        self.assertGreater(bootstrap["one_sided_95_lower_bound"], 0)
        quality = GATE.compare_quality(tasks, main, candidate)
        performance = {
            "main": {
                "dev": {"fresh_process": {"p95_ms": 10, "peak_memory_bytes": 100}},
                "warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100},
            },
            "candidate": {
                "dev": {"fresh_process": {"p95_ms": 10, "peak_memory_bytes": 100}},
                "warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100},
            },
        }

        gate = GATE.evaluate_gate(quality, bootstrap, performance)

        self.assertTrue(gate["passed"], gate["reasons"])

    def test_gate_rejects_family_safety_and_inconclusive_bootstrap_regressions(self):
        tasks = [
            task("a1", "family-a", "common"),
            task("a2", "family-a", "common"),
            task("b1", "family-b", "linux"),
            task("u1", "family-b", "linux", answerable=False),
        ]
        main = [GATE.score_ids(item, []) for item in tasks]
        candidate = [
            GATE.score_ids(tasks[0], [("good",)]),
            GATE.score_ids(tasks[1], [("wrong",)]),
            GATE.score_ids(tasks[2], []),
            GATE.score_ids(tasks[3], [("wrong",)]),
        ]
        quality = GATE.compare_quality(tasks, main, candidate)
        bootstrap = GATE.paired_bootstrap(main, candidate, resamples=100)
        performance = {
            "main": {
                "dev": {"fresh_process": {"p95_ms": 10, "peak_memory_bytes": 100}},
                "warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100},
            },
            "candidate": {
                "dev": {"fresh_process": {"p95_ms": 10, "peak_memory_bytes": 100}},
                "warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100},
            },
        }
        gate = GATE.evaluate_gate(quality, bootstrap, performance)
        self.assertFalse(gate["passed"])
        self.assertIn("fewer than two scenario families improved in Success@1", gate["reasons"])
        self.assertIn(
            "paired bootstrap one-sided 95% lower bound is not above zero",
            gate["reasons"],
        )
        self.assertTrue(any("false_answers" in reason for reason in gate["reasons"]))

    def test_performance_gate_rejects_missing_or_over_budget_measurements(self):
        passed, reasons = GATE.performance_gate(
            {
                "main": {
                    "dev": {"fresh_process": {"p95_ms": 10, "peak_memory_bytes": 100}},
                    "warmed_query": {"p95_ms": 10, "peak_memory_bytes": None},
                },
                "candidate": {
                    "dev": {"fresh_process": {"p95_ms": 13, "peak_memory_bytes": 121}},
                    "warmed_query": {"p95_ms": 13, "peak_memory_bytes": 120},
                },
            }
        )
        self.assertFalse(passed)
        self.assertIn("warmed-query peak_memory_bytes is unavailable", reasons)
        self.assertIn("warmed-query p95_ms regressed by more than 20%", reasons)
        self.assertIn("dev fresh-process p95_ms regressed by more than 20%", reasons)
        self.assertIn("dev fresh-process peak_memory_bytes regressed by more than 20%", reasons)

    def test_execution_failures_make_gate_inconclusive(self):
        tasks = [task("t1", "family-a", "common")]
        main = [GATE.score_ids(tasks[0], [("good",)])]
        candidate = [GATE.score_ids(tasks[0], [("good",)])]
        quality = GATE.compare_quality(tasks, main, candidate)
        bootstrap = GATE.paired_bootstrap(main, candidate, resamples=100)
        performance = {
            "main": {
                "dev": {"fresh_process": {"p95_ms": 10, "peak_memory_bytes": 100}},
                "warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100},
            },
            "candidate": {
                "dev": {"fresh_process": {"p95_ms": 10, "peak_memory_bytes": 100}},
                "warmed_query": {"p95_ms": 10, "peak_memory_bytes": 100},
            },
        }
        gate = GATE.evaluate_gate(
            quality,
            bootstrap,
            performance,
            {"main": [], "candidate": [{"task_id": "t1", "exit_status": 1}]},
        )
        self.assertFalse(gate["passed"])
        self.assertIn("CLI execution failures: candidate=1", gate["reasons"])

    def test_independent_holdout_gate_requires_holdout_improvement_and_no_platform_loss(self):
        def metric(count, denominator):
            return {"count": count, "denominator": denominator}

        summary = {
            "success_at_1": metric(10, 30),
            "success_at_3": metric(20, 30),
            "incorrect_answered_tasks": metric(5, 20),
            "false_answers_on_unanswerable": metric(4, 30),
        }
        improved = {
            **summary,
            "success_at_1": metric(15, 30),
            "success_at_3": metric(22, 30),
        }
        platform_main = {
            "success_at_1": metric(2, 5),
            "success_at_3": metric(3, 5),
            "incorrect_answered_tasks": metric(1, 4),
            "false_answers_on_unanswerable": metric(1, 5),
        }
        platform_candidate = {
            "success_at_1": metric(3, 5),
            "success_at_3": metric(4, 5),
            "incorrect_answered_tasks": metric(1, 4),
            "false_answers_on_unanswerable": metric(1, 5),
        }
        platform_summaries = {
            name: {"main": platform_main, "candidate": platform_candidate}
            for name in ("common", "linux", "osx", "windows")
        }
        quality = {
            "main": summary,
            "candidate": improved,
            "platform": platform_summaries,
        }
        performance = {
            "main": {
                "dev": {"fresh_process": {"p95_ms": 100, "peak_memory_bytes": 1000}},
                "holdout": {"fresh_process": {"p95_ms": 100, "peak_memory_bytes": 1000}},
                "warmed_query": {"p95_ms": 100, "peak_memory_bytes": 1000},
            },
            "candidate": {
                "dev": {"fresh_process": {"p95_ms": 110, "peak_memory_bytes": 1050}},
                "holdout": {"fresh_process": {"p95_ms": 110, "peak_memory_bytes": 1050}},
                "warmed_query": {"p95_ms": 110, "peak_memory_bytes": 1050},
            },
        }
        bootstrap = {"one_sided_95_lower_bound": 0.05}

        gate = GATE.evaluate_independent_holdout_gate(
            quality, bootstrap, performance, {"main": [], "candidate": []}
        )

        self.assertTrue(gate["passed"], gate["reasons"])

        quality["platform"]["linux"]["candidate"]["success_at_3"] = metric(2, 5)
        gate = GATE.evaluate_independent_holdout_gate(
            quality, bootstrap, performance, {"main": [], "candidate": []}
        )
        self.assertFalse(gate["passed"])
        self.assertIn(
            "independent holdout success_at_3 regressed on platform linux",
            gate["reasons"],
        )

    def test_fresh_holdout_validator_checks_frozen_distribution_without_v2_families(self):
        platforms = ("common", "linux", "osx", "windows")
        tasks = []
        distribution = {}
        for index, platform_name in enumerate(platforms):
            answerable = index % 2 == 0
            tasks.append(
                {
                    "id": f"task-{index}",
                    "split": "holdout",
                    "family": f"family-{index}",
                    "question": f"question {index}",
                    "platform": platform_name,
                    "answerable": answerable,
                    "acceptable_example_ids": [f"example-{index}"] if answerable else [],
                    "rationale": f"rationale {index}",
                }
            )
            distribution[platform_name] = {
                "tasks": 1,
                "answerable": int(answerable),
                "abstain": int(not answerable),
            }
        corpus = {
            "corpus_id": "revision:digest",
            "source_revision": "revision",
            "source_digest": "digest",
            "parser_version": "tldr-subset-v4",
        }
        dataset = {
            "split": "holdout",
            "scorer_version": GATE.evaluator.SCORER_VERSION,
            "task_count": 4,
            "corpus": corpus,
            "tasks": tasks,
        }
        freeze = {
            "intents": {"task_count": 4},
            "corpus": {
                "source_revision": "revision",
                "source_digest": "digest",
                "parser_version": "tldr-subset-v4",
            },
            "labels": {"answerable": 2, "abstain": 2},
            "distribution": distribution,
        }

        GATE.validate_fresh_holdout_dataset(dataset, freeze)

        corpus["corpus_id"] = "tldr-pages@revision"
        GATE.validate_fresh_holdout_dataset(dataset, freeze)

        corpus["corpus_id"] = "tldr-pages@other-revision"
        with self.assertRaisesRegex(ValueError, "corpus ID is inconsistent"):
            GATE.validate_fresh_holdout_dataset(dataset, freeze)

        corpus["corpus_id"] = "tldr-pages@revision"
        corpus["source_digest"] = "other-digest"
        with self.assertRaisesRegex(ValueError, "source_digest"):
            GATE.validate_fresh_holdout_dataset(dataset, freeze)
        corpus["source_digest"] = "digest"

        dataset["tasks"][0]["family"] = dataset["tasks"][1]["family"]
        with self.assertRaisesRegex(ValueError, "families must be unique"):
            GATE.validate_fresh_holdout_dataset(dataset, freeze)


if __name__ == "__main__":
    unittest.main()
