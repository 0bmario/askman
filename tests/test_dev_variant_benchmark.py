import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests/fixtures/tldr-evaluation-v2"
DATASET_PATH = ROOT / "tests/fixtures/evaluation/dev-variant-benchmark-v1.json"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
CONFIG_PATH = ROOT / "tests/fixtures/evaluation/dev-variant-hybrid-config-v1.json"
SOURCE_POLICY_CONFIG_PATH = ROOT / "tests/fixtures/evaluation/hybrid-config-expanded-dev-v1.json"
ALLOWED_SOURCE_PAGES = {
    "pages/common/find.md",
    "pages/common/grep.md",
    "pages/common/sort.md",
    "pages/linux/systemctl.md",
    "pages/osx/screencapture.md",
    "pages/windows/findstr.md",
}
SUPPORTED_PLATFORMS = {"common", "linux", "osx", "windows"}


def deterministic_id(kind: str, fields: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(b"askman-tldr-subset-id-v1\n")
    digest.update(kind.encode())
    digest.update(b"\0")
    for field in fields:
        encoded = field.encode()
        digest.update(str(len(encoded)).encode())
        digest.update(b"\0")
        digest.update(encoded)
        digest.update(b"\0")
    return f"{kind}-{digest.hexdigest()}"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_dev_variant_benchmark_schema_and_provenance() -> None:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest = json.loads(manifest_bytes)
    provenance = dataset["provenance"]

    assert dataset["dataset_id"] == "askman-dev-variant-benchmark-v1"
    assert dataset["schema_version"] == 1
    assert dataset["scorer_version"] == "task-scorer-v1"
    assert dataset["split"] == "dev"
    assert dataset["freeze_status"] == "NON-FROZEN"
    assert dataset["task_count"] == len(dataset["tasks"]) == 30
    assert provenance["source_manifest"] == str(MANIFEST_PATH.relative_to(ROOT))
    assert provenance["source_manifest_sha256"] == hashlib.sha256(
        manifest_bytes
    ).hexdigest()
    assert provenance["source_revision"] == manifest["source"]["revision"]
    assert provenance["source_digest"] == manifest["source"]["digest"]
    assert dataset["corpus"] == {
        "corpus_id": f"{manifest['source']['revision']}:{manifest['source']['digest']}",
        "artifact_kind": "askman.tldr-subset",
        "schema_version": str(manifest["schema_version"]),
        "parser_version": manifest["parser_version"],
        "source_revision": manifest["source"]["revision"],
        "source_digest": manifest["source"]["digest"],
        "manifest_sha256": provenance["source_manifest_sha256"],
    }

    source_pages = set(provenance["source_pages"])
    assert source_pages == ALLOWED_SOURCE_PAGES
    assert source_pages <= set(manifest["files"])

    task_ids: set[str] = set()
    family_counts: Counter[str] = Counter()
    answerable_count = 0
    for task in dataset["tasks"]:
        task_id = task["id"]
        assert task_id.startswith("dev-variant-v1-")
        assert task_id not in task_ids
        task_ids.add(task_id)
        assert task["split"] == "dev"
        assert task["platform"] in SUPPORTED_PLATFORMS
        assert isinstance(task["answerable"], bool)
        assert task["question"].strip()
        assert task["rationale"].strip()
        family_counts[task["family"]] += 1

        expected_example_ids: list[str] = []
        source_examples = task["source_examples"]
        assert isinstance(source_examples, list) and source_examples
        for source_example in source_examples:
            source_path = source_example["page"]
            assert source_path in source_pages
            positions = source_example["example_positions"]
            assert isinstance(positions, list)

            page_path = FIXTURE_DIR / source_path
            page_text = page_path.read_text(encoding="utf-8")
            example_count = sum(
                line.startswith("`") and line.endswith("`")
                for line in page_text.splitlines()
            )
            platform = source_path.split("/")[1]
            page_id = deterministic_id(
                "page",
                [
                    manifest["source"]["revision"],
                    source_path,
                    platform,
                    manifest["language"],
                ],
            )
            for position in positions:
                assert isinstance(position, int) and position > 0
                assert position <= example_count
                expected_example_ids.append(
                    deterministic_id("example", [page_id, str(position)])
                )

        acceptable_ids = task["acceptable_example_ids"]
        assert isinstance(acceptable_ids, list)
        assert len(acceptable_ids) == len(set(acceptable_ids))
        if task["answerable"]:
            answerable_count += 1
            assert expected_example_ids
            assert set(acceptable_ids) == set(expected_example_ids)
        else:
            assert not expected_example_ids
            assert acceptable_ids == []

    assert len(task_ids) == 30
    assert family_counts == {
        "variant-common-sort": 5,
        "variant-common-find": 5,
        "variant-linux-systemctl": 5,
        "variant-osx-screencapture": 5,
        "variant-windows-findstr": 5,
        "guardrail-out-of-scope-or-ambiguous": 5,
    }
    assert dataset["answerable_task_count"] == answerable_count == 25
    assert dataset["unanswerable_task_count"] == len(dataset["tasks"]) - answerable_count == 5


def validate_dev_variant_hybrid_config_is_non_frozen_and_bound_to_inputs() -> None:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    source_policy = json.loads(SOURCE_POLICY_CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["config_id"] == "dev-variant-hybrid-v1"
    assert config["freeze_status"] == "NON-FROZEN"
    assert config["candidate_id"] == "hybrid"
    assert config["split"] == "dev"
    assert config["dataset"] == {
        "dataset_id": dataset["dataset_id"],
        "sha256": sha256_file(DATASET_PATH),
    }
    assert config["corpus"] == dataset["corpus"]
    assert config["source_policy_config"] == {
        "path": str(SOURCE_POLICY_CONFIG_PATH.relative_to(ROOT)),
        "sha256": sha256_file(SOURCE_POLICY_CONFIG_PATH),
    }
    assert config["policy"] == source_policy["policy"]
    assert config["source_manifest"]["sha256"] == dataset["provenance"][
        "source_manifest_sha256"
    ]
    assert config["runtime"]["onnxruntime_version"] == "1.20.0"


class TestDevVariantBenchmark(unittest.TestCase):
    def test_schema_and_provenance(self) -> None:
        validate_dev_variant_benchmark_schema_and_provenance()

    def test_hybrid_config_is_non_frozen_and_bound_to_inputs(self) -> None:
        validate_dev_variant_hybrid_config_is_non_frozen_and_bound_to_inputs()
