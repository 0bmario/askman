#!/usr/bin/env python3
"""Evaluate retrieval against the frozen, source-backed milestone-1 tasks.

The runner deliberately talks to the validated SQLite artifact, not the
shipping Askman database.  It therefore has no network path and keeps task
questions, labels, and rationales outside the retrieval index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DATASET_SCHEMA_VERSION = 1
SCORER_VERSION = "task-scorer-v1"
KEYWORD_RETRIEVER_VERSION = "keyword-fts5-v1"
CURRENT_ADAPTER_VERSION = "current-askman-ranking-adapter-v1"
DENSE_RETRIEVER_VERSION = "dense-vector-vec0-v1"
HYBRID_RETRIEVER_VERSION = "hybrid-rrf-v1"
HYBRID_CONFIG_SCHEMA_VERSION = 1
FROZEN_HYBRID_CONFIG_SHA256 = (
    "1059c9bf72e570cf431ccddb2676176bac65238b5c4c8a07b63891e5133a9c7f"
)
SUPPORTED_PLATFORMS = {"common", "linux", "osx", "windows"}
MAX_DISPLAYED_RESULTS = 3
EXPECTED_FAMILIES_PER_SPLIT = 6
TASKS_PER_FAMILY = 5
HYBRID_MAX_CANDIDATES = 12
HYBRID_PLATFORM_POLICY = "artifact-selected-page-ids-v1"
HYBRID_REFERENCE_POLICY = (
    "source-backed-pages-only; page references never substitute examples"
)
HYBRID_CORPUS_FIELDS = (
    "corpus_id",
    "artifact_kind",
    "schema_version",
    "parser_version",
    "source_revision",
    "source_digest",
    "manifest_sha256",
)
HYBRID_SELECTION_RULE = {
    "primary_metric": "success_at_3",
    "tie_breakers": [
        "candidate_recall",
        "coverage",
        "total_candidate_budget",
        "rrf_k",
    ],
    "guardrails": [
        "do not increase false_answers_on_unanswerable",
        "retain keyword and dense baselines",
    ],
    "text": (
        "Maximize Success@3; break ties by candidate recall, coverage, lower "
        "total candidate budget, then lower RRF k, subject to the false-answer "
        "guardrail."
    ),
}
FROZEN_METRICS = (
    "candidate_recall",
    "success_at_1",
    "success_at_3",
    "coverage",
    "incorrect_answered_tasks",
    "false_answers_on_unanswerable",
)
EXPECTED_DEV_METRIC_DENOMINATORS = {
    "candidate_recall": 13,
    "success_at_1": 13,
    "success_at_3": 13,
    "coverage": 30,
    "incorrect_answered_tasks": 13,
    "false_answers_on_unanswerable": 17,
}
LEXICAL_INDEX_TOKENIZER = "unicode61"
LEXICAL_INDEX_FIELDS = [
    "page.command",
    "page.description",
    "example.description",
    "example.command",
]
LEXICAL_QUERY_NORMALIZATION = (
    "split non-alphanumeric except underscore; lowercase ASCII; "
    "quote and AND-join unique sorted tokens"
)
OFFICIAL_SOURCE_MARKERS = (
    "gnu.",
    "kernel.",
    "man7.",
    "manned.",
    "linux.",
    "man.openbsd",
    "man.freebsd",
    "greenwoodsoftware.",
)


@dataclass(frozen=True)
class Candidate:
    example_id: str
    page_id: str
    command: str
    page_description: str
    example_description: str
    source_path: str
    source_ref: str
    source_revision: str
    platform: str
    page_position: int
    example_position: int
    ranking_score: float


@dataclass(frozen=True)
class HybridCandidateConfig:
    candidate_id: str
    rrf_k: int
    keyword_weight: float
    dense_weight: float
    keyword_budget: int
    dense_budget: int
    weak_match_cutoff: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "fusion": {
                "method": "rrf",
                "rrf_k": self.rrf_k,
                "keyword_weight": self.keyword_weight,
                "dense_weight": self.dense_weight,
            },
            "candidate_budgets": {
                "keyword": self.keyword_budget,
                "dense": self.dense_budget,
            },
            "weak_match_cutoff": self.weak_match_cutoff,
        }


@dataclass(frozen=True)
class HybridConfig:
    config_id: str
    frozen: bool
    frozen_at: str
    dataset_id: str
    split_id: str
    corpus: dict[str, str]
    dense_recipe: str
    corpus_policy: str
    reference_policy: str
    retriever_versions: dict[str, str]
    metrics: tuple[str, ...]
    selection_rule: dict[str, Any]
    candidates: tuple[HybridCandidateConfig, ...]
    selected_candidate_id: str
    development_results: dict[str, Any]

    @property
    def selected(self) -> HybridCandidateConfig:
        return next(
            candidate
            for candidate in self.candidates
            if candidate.candidate_id == self.selected_candidate_id
        )


def query_resources(query_times_ms: list[float]) -> dict[str, Any]:
    sorted_times = sorted(query_times_ms)

    def percentile(percent: float) -> float | None:
        if not sorted_times:
            return None
        index = min(
            len(sorted_times) - 1,
            int((len(sorted_times) * percent) + 0.999999) - 1,
        )
        return round(sorted_times[index], 3)

    return {
        "repeated_query_count": len(sorted_times),
        "repeated_query_p50_ms": percentile(0.50),
        "repeated_query_p95_ms": percentile(0.95),
    }


class DenseClient:
    def __init__(self, helper: Path, artifact: Path, model_cache: Path) -> None:
        started = time.perf_counter()
        try:
            self.process = subprocess.Popen(
                [
                    str(helper),
                    "dense-server",
                    "--artifact",
                    str(artifact),
                    "--model-cache",
                    str(model_cache),
                ],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as error:
            raise RuntimeError(f"failed to start dense helper {helper}: {error}") from error
        self.query_times_ms: list[float] = []
        ready_line = self.process.stdout.readline() if self.process.stdout else ""
        if not ready_line:
            error = self.process.stderr.read() if self.process.stderr else ""
            self.close(check=False)
            raise RuntimeError(
                f"dense helper failed during model/index startup: {error.strip()}"
            )
        try:
            ready = json.loads(ready_line)
        except json.JSONDecodeError as error:
            self.close(check=False)
            raise RuntimeError("dense helper returned invalid startup metadata") from error
        if not ready.get("ready"):
            self.close(check=False)
            raise RuntimeError("dense helper did not become ready")
        self.model_load_ms = ready.get("model_load_ms")
        self.peak_memory_bytes = ready.get("peak_memory_bytes")
        self.startup_ms = (time.perf_counter() - started) * 1000

    def query(
        self, question: str, platform: str, limit: int = MAX_DISPLAYED_RESULTS
    ) -> list[Candidate]:
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("dense helper is not connected")
        if limit <= 0:
            raise ValueError("dense candidate budget must be greater than zero")
        request = json.dumps(
            {"query": question, "platform": platform, "limit": limit}
        )
        started = time.perf_counter()
        try:
            self.process.stdin.write(request + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
        except (BrokenPipeError, OSError) as error:
            raise RuntimeError(f"dense helper query failed: {error}") from error
        self.query_times_ms.append((time.perf_counter() - started) * 1000)
        if not line:
            error = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"dense helper exited during query: {error.strip()}")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "dense helper query failed"))
        return [Candidate(**candidate) for candidate in response["results"]]

    def resources(self) -> dict[str, Any]:
        resources = query_resources(self.query_times_ms)
        resources.update(
            {
                "helper_startup_ms": round(self.startup_ms, 3),
                "model_load_ms": self.model_load_ms,
                "peak_memory_bytes": self.peak_memory_bytes,
            }
        )
        return resources

    def close(self, check: bool = True) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            return_code = self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            return_code = self.process.wait(timeout=5)
        if check and return_code != 0:
            raise RuntimeError(
                f"dense helper exited with status {return_code}; "
                "check the pinned ONNX Runtime and model assets"
            )


def validate_retriever_split(retriever: str, split: str) -> None:
    if retriever == "dense" and split != "dev":
        raise ValueError(
            "dense retrieval evaluation is development-only; holdout access belongs "
            "to later comparison/evidence tickets"
        )


def baseline_resources(query_times_ms: list[float]) -> dict[str, Any]:
    resources = query_resources(query_times_ms)
    resources.update(
        {
            "helper_startup_ms": None,
            "model_load_ms": None,
            "peak_memory_bytes": None,
        }
    )
    return resources


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _require_non_empty_string(value: Any, name: str) -> str:
    is_non_empty_string = isinstance(value, str) and bool(value.strip())
    if not is_non_empty_string:
        raise ValueError(f"hybrid config {name} must be a non-empty string")
    return value


def _require_bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    is_valid_integer = (
        not isinstance(value, bool)
        and isinstance(value, int)
        and minimum <= value <= maximum
    )
    if not is_valid_integer:
        raise ValueError(
            f"hybrid config {name} must be an integer from {minimum} through {maximum}"
        )
    return value


def _require_bounded_float(value: Any, name: str, minimum: float, maximum: float) -> float:
    is_number = not isinstance(value, bool) and isinstance(value, (int, float))
    if not is_number:
        raise ValueError(f"hybrid config {name} must be a number")
    converted = float(value)
    is_in_range = math.isfinite(converted) and minimum <= converted <= maximum
    if not is_in_range:
        raise ValueError(
            f"hybrid config {name} must be finite and from {minimum} through {maximum}"
        )
    return converted


def _require_metric_record(value: Any, name: str) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        raise ValueError(f"hybrid config {name} must be an object")
    result: dict[str, dict[str, int]] = {}
    for metric in FROZEN_METRICS:
        metric_value = value.get(metric)
        has_metric_pair = isinstance(metric_value, dict) and {
            "count",
            "denominator",
        } <= metric_value.keys()
        if not has_metric_pair:
            raise ValueError(f"hybrid config {name} is missing metric {metric}")
        count = metric_value["count"]
        denominator = metric_value["denominator"]
        has_valid_counts = (
            isinstance(count, int)
            and not isinstance(count, bool)
            and isinstance(denominator, int)
            and not isinstance(denominator, bool)
            and 0 <= count <= denominator
            and denominator > 0
            and denominator == EXPECTED_DEV_METRIC_DENOMINATORS[metric]
        )
        if not has_valid_counts:
            raise ValueError(f"hybrid config {name}.{metric} has invalid counts")
        result[metric] = {"count": count, "denominator": denominator}
    return result


def load_hybrid_config(path: Path) -> HybridConfig:
    raw = load_json(path)
    if raw.get("schema_version") != HYBRID_CONFIG_SCHEMA_VERSION:
        raise ValueError("unsupported hybrid config schema")
    config_id = _require_non_empty_string(raw.get("config_id"), "config_id")
    frozen = raw.get("frozen")
    if not isinstance(frozen, bool):
        raise ValueError("hybrid config frozen must be a boolean")
    frozen_at = _require_non_empty_string(raw.get("frozen_at"), "frozen_at")
    try:
        datetime.fromisoformat(frozen_at)
    except ValueError as error:
        raise ValueError("hybrid config frozen_at must be an ISO-8601 timestamp") from error
    dataset_id = _require_non_empty_string(raw.get("dataset_id"), "dataset_id")
    split_id = _require_non_empty_string(raw.get("split_id"), "split_id")
    dense_recipe = _require_non_empty_string(raw.get("dense_recipe"), "dense_recipe")
    raw_corpus = raw.get("corpus")
    has_corpus_fields = isinstance(raw_corpus, dict) and all(
        isinstance(raw_corpus.get(field), str) and raw_corpus[field]
        for field in HYBRID_CORPUS_FIELDS
    )
    if not has_corpus_fields:
        raise ValueError("hybrid config must declare the frozen corpus identity")
    corpus = {field: raw_corpus[field] for field in HYBRID_CORPUS_FIELDS}
    if raw.get("corpus_policy") != HYBRID_PLATFORM_POLICY:
        raise ValueError("hybrid config corpus/platform policy is incompatible")
    if raw.get("reference_policy") != HYBRID_REFERENCE_POLICY:
        raise ValueError("hybrid config reference policy is incompatible")

    retriever_versions = raw.get("retriever_versions")
    expected_versions = {
        "keyword": KEYWORD_RETRIEVER_VERSION,
        "dense": DENSE_RETRIEVER_VERSION,
    }
    if retriever_versions != expected_versions:
        raise ValueError("hybrid config retriever versions are incompatible")

    metrics = raw.get("metrics")
    if metrics != list(FROZEN_METRICS):
        raise ValueError("hybrid config metrics are not frozen to the evaluator metrics")
    selection_rule = raw.get("selection_rule")
    if selection_rule != HYBRID_SELECTION_RULE:
        raise ValueError("hybrid config selection rule is not frozen")

    raw_candidates = raw.get("candidates")
    has_bounded_candidate_list = isinstance(raw_candidates, list) and (
        1 <= len(raw_candidates) <= HYBRID_MAX_CANDIDATES
    )
    if not has_bounded_candidate_list:
        raise ValueError(
            f"hybrid config must contain from 1 through {HYBRID_MAX_CANDIDATES} candidates"
        )
    candidates: list[HybridCandidateConfig] = []
    candidate_ids: set[str] = set()
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict):
            raise ValueError("hybrid config candidates must be objects")
        candidate_id = _require_non_empty_string(raw_candidate.get("id"), "candidate id")
        if candidate_id in candidate_ids:
            raise ValueError(f"hybrid config repeats candidate id: {candidate_id}")
        candidate_ids.add(candidate_id)
        fusion = raw_candidate.get("fusion")
        is_rrf_fusion = isinstance(fusion, dict) and fusion.get("method") == "rrf"
        if not is_rrf_fusion:
            raise ValueError(f"hybrid candidate {candidate_id} must use rrf fusion")
        budgets = raw_candidate.get("candidate_budgets")
        if not isinstance(budgets, dict):
            raise ValueError(f"hybrid candidate {candidate_id} is missing candidate budgets")
        candidates.append(
            HybridCandidateConfig(
                candidate_id=candidate_id,
                rrf_k=_require_bounded_int(
                    fusion.get("rrf_k"), f"{candidate_id}.fusion.rrf_k", 1, 1000
                ),
                keyword_weight=_require_bounded_float(
                    fusion.get("keyword_weight"),
                    f"{candidate_id}.fusion.keyword_weight",
                    0.01,
                    4.0,
                ),
                dense_weight=_require_bounded_float(
                    fusion.get("dense_weight"),
                    f"{candidate_id}.fusion.dense_weight",
                    0.01,
                    4.0,
                ),
                keyword_budget=_require_bounded_int(
                    budgets.get("keyword"), f"{candidate_id}.candidate_budgets.keyword", 1, 64
                ),
                dense_budget=_require_bounded_int(
                    budgets.get("dense"), f"{candidate_id}.candidate_budgets.dense", 1, 64
                ),
                weak_match_cutoff=_require_bounded_float(
                    raw_candidate.get("weak_match_cutoff"),
                    f"{candidate_id}.weak_match_cutoff",
                    0.0,
                    1.0,
                ),
            )
        )

    selected_candidate_id = _require_non_empty_string(
        raw.get("selected_candidate_id"), "selected_candidate_id"
    )
    if selected_candidate_id not in candidate_ids:
        raise ValueError("hybrid config selected candidate is not in the candidate set")
    raw_development_results = raw.get("development_results")
    has_development_results = (
        isinstance(raw_development_results, dict)
        and raw_development_results.get("split") == "dev"
        and raw_development_results.get("task_count") == 30
        and isinstance(raw_development_results.get("baselines"), dict)
        and isinstance(raw_development_results.get("candidates"), dict)
    )
    if not has_development_results:
        raise ValueError("hybrid config must record development results")
    raw_baselines = raw_development_results["baselines"]
    baseline_names = {"keyword", "current-adapter", "dense"}
    has_expected_baselines = set(raw_baselines) == baseline_names
    if not has_expected_baselines:
        raise ValueError("hybrid config must retain keyword, current-adapter, and dense baselines")
    development_results: dict[str, Any] = {
        "baselines": {
            name: _require_metric_record(raw_baselines[name], f"baseline {name}")
            for name in sorted(baseline_names)
        },
        "candidates": {},
    }
    raw_candidate_results = raw_development_results["candidates"]
    has_all_candidate_results = set(raw_candidate_results) == candidate_ids
    if not has_all_candidate_results:
        raise ValueError("hybrid config development results must cover every candidate")
    for candidate_id in sorted(candidate_ids):
        development_results["candidates"][candidate_id] = _require_metric_record(
            raw_candidate_results[candidate_id], f"candidate {candidate_id}"
        )
    config = HybridConfig(
        config_id=config_id,
        frozen=frozen,
        frozen_at=frozen_at,
        dataset_id=dataset_id,
        split_id=split_id,
        corpus=corpus,
        dense_recipe=dense_recipe,
        corpus_policy=raw["corpus_policy"],
        reference_policy=raw["reference_policy"],
        retriever_versions=retriever_versions,
        metrics=tuple(metrics),
        selection_rule=selection_rule,
        candidates=tuple(candidates),
        selected_candidate_id=selected_candidate_id,
        development_results=development_results,
    )
    selected_by_rule = select_development_candidate(config)
    if selected_by_rule != config.selected_candidate_id:
        raise ValueError("hybrid config selected candidate does not match development results")
    return config


def select_development_candidate(config: HybridConfig) -> str:
    """Apply the frozen development selection rule to recorded metrics."""
    baseline_false_answers = config.development_results["baselines"]["keyword"][
        "false_answers_on_unanswerable"
    ]
    baseline_false_rate = (
        baseline_false_answers["count"] / baseline_false_answers["denominator"]
    )
    candidate_by_id = {candidate.candidate_id: candidate for candidate in config.candidates}
    eligible: list[HybridCandidateConfig] = []
    for candidate_id, metrics in config.development_results["candidates"].items():
        false_answers = metrics["false_answers_on_unanswerable"]
        false_answer_rate = false_answers["count"] / false_answers["denominator"]
        does_not_increase_false_answers = false_answer_rate <= baseline_false_rate
        if does_not_increase_false_answers:
            eligible.append(candidate_by_id[candidate_id])
    if not eligible:
        raise ValueError("hybrid config has no candidate satisfying the false-answer guardrail")

    def metric_rate(candidate_id: str, metric: str) -> float:
        value = config.development_results["candidates"][candidate_id][metric]
        return value["count"] / value["denominator"]

    return min(
        eligible,
        key=lambda candidate: (
            -metric_rate(candidate.candidate_id, "success_at_3"),
            -metric_rate(candidate.candidate_id, "candidate_recall"),
            -metric_rate(candidate.candidate_id, "coverage"),
            candidate.keyword_budget + candidate.dense_budget,
            candidate.rrf_k,
            candidate.candidate_id,
        ),
    ).candidate_id


def hybrid_candidate_report(config: HybridCandidateConfig) -> dict[str, Any]:
    return config.as_dict()


def normalized_tokens(question: str) -> list[str]:
    tokens = {
        token.lower()
        for token in re.split(r"[^A-Za-z0-9_]+", question)
        if token
    }
    return sorted(tokens)


def fts_query(question: str) -> str:
    tokens = normalized_tokens(question)
    if not tokens:
        raise ValueError("query contains no searchable tokens")
    return " AND ".join(f'"{token.replace(chr(34), chr(34) + chr(34))}"' for token in tokens)


def metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return dict(connection.execute("SELECT key, value FROM artifact_metadata"))


def selected_page_ids(connection: sqlite3.Connection, platform: str) -> set[str]:
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"unsupported platform: {platform}")
    rows = connection.execute(
        "SELECT page_id, page_name, platform FROM pages ORDER BY page_position"
    )
    pages = list(rows)
    names = {row[1] for row in pages}
    selected: set[str] = set()
    for name in names:
        target = next(
            (row for row in pages if row[1] == name and row[2] == platform), None
        )
        common = next(
            (row for row in pages if row[1] == name and row[2] == "common"), None
        )
        chosen = target or common
        if chosen:
            selected.add(chosen[0])
    return selected


def fetch_candidates(
    connection: sqlite3.Connection,
    question: str,
    platform: str,
    limit: int | None = None,
) -> list[Candidate]:
    if limit is not None and limit <= 0:
        raise ValueError("keyword candidate budget must be greater than zero")
    page_ids = sorted(selected_page_ids(connection, platform))
    if not page_ids:
        return []
    placeholders = ",".join("?" for _ in page_ids)
    rows = connection.execute(
        f"""SELECT e.example_id, e.page_id, e.command, p.description, e.description,
                   p.source_path, p.source_ref, p.source_revision, p.platform,
                   p.page_position, e.position, bm25(example_lexical)
            FROM example_lexical
            JOIN examples AS e ON e.example_id = example_lexical.example_id
            JOIN pages AS p ON p.page_id = e.page_id
            WHERE example_lexical MATCH ? AND p.page_id IN ({placeholders})
            ORDER BY bm25(example_lexical), e.example_id""",
        (fts_query(question), *page_ids),
    )
    candidates = [Candidate(*row) for row in rows]
    if limit is None:
        return candidates
    # Dense retrieval already returns one best example per page. Use the same
    # page-level budget for the lexical side so fusion ranks comparable pools.
    return one_per_page(candidates)[:limit]


def one_per_page(candidates: Iterable[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    result = []
    for candidate in candidates:
        if candidate.page_id in seen:
            continue
        seen.add(candidate.page_id)
        result.append(candidate)
    return result


def plain_results(candidates: list[Candidate]) -> list[Candidate]:
    return one_per_page(candidates)[:MAX_DISPLAYED_RESULTS]


def candidate_identity(candidate: Candidate) -> tuple[Any, ...]:
    """Return the source-backed identity shared by lexical and dense rows."""
    return (
        candidate.page_id,
        candidate.command,
        candidate.page_description,
        candidate.example_description,
        candidate.source_path,
        candidate.source_ref,
        candidate.source_revision,
        candidate.platform,
        candidate.page_position,
        candidate.example_position,
    )


def fuse_candidates(
    keyword_candidates: list[Candidate],
    dense_candidates: list[Candidate],
    config: HybridCandidateConfig,
) -> list[Candidate]:
    """Fuse bounded retriever pools with normalized reciprocal-rank fusion.

    Candidate recall is measured from this pre-cutoff pool. Weak-match filtering
    happens only in `hybrid_results`, after page grouping.
    """
    by_id: dict[str, Candidate] = {}
    fused_scores: dict[str, float] = {}
    sources = (
        (one_per_page(keyword_candidates)[: config.keyword_budget], config.keyword_weight),
        (one_per_page(dense_candidates)[: config.dense_budget], config.dense_weight),
    )
    for candidates, weight in sources:
        for rank, candidate in enumerate(candidates, start=1):
            previous = by_id.get(candidate.example_id)
            has_conflicting_identity = (
                previous is not None
                and candidate_identity(previous) != candidate_identity(candidate)
            )
            if has_conflicting_identity:
                raise ValueError(
                    "candidate identity mismatch for "
                    f"{candidate.example_id} between keyword and dense retrieval"
                )
            by_id.setdefault(candidate.example_id, candidate)
            fused_scores[candidate.example_id] = fused_scores.get(candidate.example_id, 0.0) + (
                weight / (config.rrf_k + rank)
            )

    maximum_score = (
        config.keyword_weight / (config.rrf_k + 1)
        + config.dense_weight / (config.rrf_k + 1)
    )
    ranked = sorted(
        by_id,
        key=lambda example_id: (-fused_scores[example_id], example_id),
    )
    return [
        replace(
            by_id[example_id],
            # Lower remains better for the existing Candidate/report shape.
            ranking_score=-(fused_scores[example_id] / maximum_score),
        )
        for example_id in ranked
    ]


def hybrid_results(
    candidates: list[Candidate], config: HybridCandidateConfig
) -> list[Candidate]:
    """Display close candidates as at most three distinct destination pages."""
    close_matches = [
        candidate
        for candidate in candidates
        # A strict boundary makes the 0.5 score of a one-retriever-only top hit
        # weak when both retrievers have equal weight.
        if -candidate.ranking_score > config.weak_match_cutoff
    ]
    return plain_results(close_matches)


def current_adjustment(candidate: Candidate, raw_distance: float) -> float | None:
    """Adapt the current Rust ranking heuristics to lexical candidates.

    The released ranker filters and adjusts MiniLM L2 distances. This adapter preserves
    its filtering and command/domain multipliers while using a deterministic
    normalized FTS distance so both controlled baselines share one candidate
    pool.  It is intentionally not the historical-policy smoke run.
    """
    if raw_distance > 1.10:
        return None
    score = raw_distance
    description = candidate.page_description
    command = candidate.command
    if is_official_source(description):
        score *= 0.8
    if is_core_command(command):
        score *= 0.67
    elif is_niche_variant(command):
        score *= 1.33
    return score


def is_official_source(description: str) -> bool:
    return any(marker in description for marker in OFFICIAL_SOURCE_MARKERS)


def is_core_command(command: str) -> bool:
    return command == "grep" or (
        len(command) <= 3
        and not command.startswith("q")
        and not command.startswith("z")
    )


def is_niche_variant(command: str) -> bool:
    return (
        "-" in command
        or command.startswith("q")
        or command.startswith("z")
        or (command.endswith("grep") and command != "grep")
        or command.endswith("all")
    )


def current_adapter_results(candidates: list[Candidate]) -> list[Candidate]:
    if not candidates:
        return []
    scores = [candidate.ranking_score for candidate in candidates]
    low, high = min(scores), max(scores)
    span = high - low
    by_page: dict[str, tuple[float, Candidate]] = {}
    for candidate in candidates:
        relative = 0.5 if span == 0 else (candidate.ranking_score - low) / span
        raw_distance = 0.5 + (relative * 0.6)
        adjusted = current_adjustment(candidate, raw_distance)
        if adjusted is None:
            continue
        previous = by_page.get(candidate.page_id)
        is_better_candidate = previous is None or (adjusted, candidate.example_id) < (
            previous[0],
            previous[1].example_id,
        )
        if is_better_candidate:
            by_page[candidate.page_id] = (adjusted, candidate)
    ranked = sorted(
        by_page.values(), key=lambda item: (item[0], item[1].example_id)
    )
    return [candidate for _, candidate in ranked[:MAX_DISPLAYED_RESULTS]]


def score_task(
    task: dict[str, Any], displayed: list[Candidate], candidates: list[Candidate]
) -> dict[str, Any]:
    acceptable = set(task["acceptable_example_ids"])
    answerable = task["answerable"]
    displayed_ids = [candidate.example_id for candidate in displayed]
    candidate_ids = {candidate.example_id for candidate in candidates}
    hit_at_1 = bool(displayed_ids and displayed_ids[0] in acceptable)
    hit_at_3 = any(example_id in acceptable for example_id in displayed_ids[:3])
    candidate_hit = bool(acceptable & candidate_ids) if answerable else False
    answered = bool(displayed_ids)
    return {
        "task_id": task["id"],
        "displayed_example_ids": displayed_ids,
        "candidate_example_ids": [candidate.example_id for candidate in candidates],
        "success_at_1": hit_at_1 if answerable else False,
        "success_at_3": hit_at_3 if answerable else False,
        "candidate_recall": candidate_hit if answerable else None,
        "answered": answered,
        "incorrect_answer": answerable and answered and not hit_at_3,
        "false_answer": not answerable and answered,
    }


def summarize(tasks: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [task for task in tasks if task["answerable"]]
    unanswerable = [task for task in tasks if not task["answerable"]]
    by_id = {result["task_id"]: result for result in results}
    answerable_results = [by_id[task["id"]] for task in answerable]
    answered = [result for result in results if result["answered"]]
    answered_answerable = [result for result in answerable_results if result["answered"]]
    return {
        "tasks": len(tasks),
        "answerable_tasks": len(answerable),
        "unanswerable_tasks": len(unanswerable),
        "success_at_1": {
            "count": sum(result["success_at_1"] for result in answerable_results),
            "denominator": len(answerable),
        },
        "success_at_3": {
            "count": sum(result["success_at_3"] for result in answerable_results),
            "denominator": len(answerable),
        },
        "candidate_recall": {
            "count": sum(result["candidate_recall"] for result in answerable_results),
            "denominator": len(answerable),
        },
        "coverage": {"count": len(answered), "denominator": len(tasks)},
        "incorrect_answered_tasks": {
            "count": sum(result["incorrect_answer"] for result in results),
            "denominator": len(answered_answerable),
        },
        "false_answers_on_unanswerable": {
            "count": sum(result["false_answer"] for result in results),
            "denominator": len(unanswerable),
        },
    }


def validate_dataset(dataset: dict[str, Any], expected_split: str) -> None:
    if dataset.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported evaluation dataset schema")
    if dataset.get("scorer_version") != SCORER_VERSION:
        raise ValueError("unsupported scorer version")
    if dataset.get("split") != expected_split:
        raise ValueError(f"dataset split must be {expected_split}")
    tasks = dataset.get("tasks")
    if dataset.get("task_count") != EXPECTED_FAMILIES_PER_SPLIT * TASKS_PER_FAMILY:
        raise ValueError("each frozen split must declare exactly 30 tasks")
    has_wrong_task_list = not isinstance(tasks, list) or len(
        tasks
    ) != EXPECTED_FAMILIES_PER_SPLIT * TASKS_PER_FAMILY
    if has_wrong_task_list:
        raise ValueError("each frozen split must contain exactly 30 tasks")
    has_wrong_split = any(task.get("split") != expected_split for task in tasks)
    if has_wrong_split:
        raise ValueError(f"all tasks must belong to the {expected_split} split")
    task_ids: set[str] = set()
    families: dict[str, set[str]] = {}
    family_counts: dict[str, int] = {}
    for task in tasks:
        required = {"id", "split", "family", "question", "platform", "answerable", "acceptable_example_ids", "rationale"}
        if not required <= task.keys():
            raise ValueError(f"task {task.get('id')} is missing required labels")
        task_id = task["id"]
        has_invalid_task_id = (
            not isinstance(task_id, str) or not task_id or task_id in task_ids
        )
        if has_invalid_task_id:
            raise ValueError(f"task IDs must be unique and non-empty: {task.get('id')}")
        task_ids.add(task_id)
        has_empty_question = (
            not isinstance(task["question"], str) or not task["question"].strip()
        )
        if has_empty_question:
            raise ValueError(f"task {task['id']} has an empty question")
        family = task["family"]
        if not isinstance(family, str) or not family:
            raise ValueError(f"task {task['id']} has an invalid family")
        if task["platform"] not in SUPPORTED_PLATFORMS:
            raise ValueError(f"task {task['id']} has unsupported platform")
        if not isinstance(task["answerable"], bool):
            raise ValueError(f"task {task['id']} has an invalid answerable label")
        has_empty_rationale = (
            not isinstance(task["rationale"], str) or not task["rationale"].strip()
        )
        if has_empty_rationale:
            raise ValueError(f"task {task['id']} has an empty rationale")
        ids = task["acceptable_example_ids"]
        has_invalid_example_ids = not isinstance(ids, list) or any(
            not isinstance(example_id, str) for example_id in ids
        )
        if has_invalid_example_ids:
            raise ValueError(f"task {task['id']} has invalid acceptable example IDs")
        has_duplicate_example_ids = len(ids) != len(set(ids))
        if has_duplicate_example_ids:
            raise ValueError(f"task {task['id']} repeats an acceptable example ID")
        has_unexpected_acceptable_ids = (
            not task["answerable"] and task["acceptable_example_ids"]
        )
        if has_unexpected_acceptable_ids:
            raise ValueError(f"unanswerable task {task['id']} has acceptable IDs")
        has_missing_acceptable_ids = task["answerable"] and not task[
            "acceptable_example_ids"
        ]
        if has_missing_acceptable_ids:
            raise ValueError(f"answerable task {task['id']} has no acceptable IDs")
        families.setdefault(family, set()).add(task["split"])
        family_counts[family] = family_counts.get(family, 0) + 1
    has_wrong_family_count = len(families) != EXPECTED_FAMILIES_PER_SPLIT
    if has_wrong_family_count:
        raise ValueError("each frozen split must contain exactly six scenario families")
    has_wrong_tasks_per_family = any(
        count != TASKS_PER_FAMILY for count in family_counts.values()
    )
    if has_wrong_tasks_per_family:
        raise ValueError("each scenario family must contain exactly five tasks")
    has_cross_split_family = any(len(splits) != 1 for splits in families.values())
    if has_cross_split_family:
        raise ValueError("scenario families must not cross the dev/holdout split")


def validate_labels(
    connection: sqlite3.Connection, tasks: list[dict[str, Any]]
) -> None:
    eligible_by_platform: dict[str, set[str]] = {}
    for platform in SUPPORTED_PLATFORMS:
        page_ids = selected_page_ids(connection, platform)
        placeholders = ",".join("?" for _ in page_ids)
        if not page_ids:
            eligible_by_platform[platform] = set()
            continue
        rows = connection.execute(
            f"""SELECT lexical.example_id
                FROM example_lexical AS lexical
                JOIN examples AS e ON e.example_id = lexical.example_id
                WHERE e.page_id IN ({placeholders})""",
            tuple(sorted(page_ids)),
        )
        eligible_by_platform[platform] = {row[0] for row in rows}

    for task in tasks:
        if not task["answerable"]:
            continue
        invalid_ids = set(task["acceptable_example_ids"]) - eligible_by_platform[
            task["platform"]
        ]
        if invalid_ids:
            raise ValueError(
                f"task {task['id']} labels examples outside the selected {task['platform']} corpus: "
                + ", ".join(sorted(invalid_ids))
            )


def validate_artifact(
    connection: sqlite3.Connection, dataset: dict[str, Any], manifest: Path | None
) -> dict[str, str]:
    actual = metadata(connection)
    frozen = dataset["corpus"]
    checks = {
        "artifact_kind": actual.get("artifact_kind"),
        "schema_version": actual.get("schema_version"),
        "parser_version": actual.get("parser_version"),
        "source_revision": actual.get("source_revision"),
        "source_digest": actual.get("source_digest"),
    }
    for key, expected in frozen.items():
        if key in {"manifest_sha256", "corpus_id"}:
            continue
        if checks.get(key) != expected:
            raise ValueError(
                f"frozen corpus mismatch for {key}: expected {expected}, got {checks.get(key)}; "
                "labels are invalid for this artifact"
            )
    expected_lexical_recipe = {
        "lexical_index_tokenizer": LEXICAL_INDEX_TOKENIZER,
        "lexical_index_fields": json.dumps(LEXICAL_INDEX_FIELDS, separators=(",", ":")),
        "lexical_query_normalization": LEXICAL_QUERY_NORMALIZATION,
    }
    for key, expected in expected_lexical_recipe.items():
        if actual.get(key) != expected:
            raise ValueError(f"artifact lexical recipe mismatch for {key}")
    actual_corpus_id = f"{checks['source_revision']}:{checks['source_digest']}"
    if frozen.get("corpus_id") != actual_corpus_id:
        raise ValueError("frozen corpus ID mismatch; migrate labels explicitly")
    if manifest is not None:
        actual_manifest_digest = sha256_file(manifest)
        if actual_manifest_digest != frozen["manifest_sha256"]:
            raise ValueError("frozen corpus manifest digest mismatch; migrate labels explicitly")
    elif frozen.get("manifest_sha256"):
        raise ValueError("--manifest is required to verify the frozen corpus selection")
    return checks


def validate_hybrid_config_for_dataset(
    config: HybridConfig, dataset: dict[str, Any]
) -> None:
    if config.dataset_id != dataset.get("dataset_id"):
        raise ValueError("hybrid config dataset ID does not match the evaluation dataset")
    if config.split_id != dataset.get("split_id"):
        raise ValueError("hybrid config split policy does not match the evaluation dataset")
    dataset_corpus = dataset.get("corpus")
    has_corpus_fields = isinstance(dataset_corpus, dict) and all(
        field in dataset_corpus for field in HYBRID_CORPUS_FIELDS
    )
    if not has_corpus_fields:
        raise ValueError("evaluation dataset is missing the frozen corpus identity")
    expected_corpus = {
        field: dataset_corpus[field] for field in HYBRID_CORPUS_FIELDS
    }
    if config.corpus != expected_corpus:
        raise ValueError(
            "hybrid config corpus identity does not match the evaluation dataset"
        )


def validate_hybrid_config_for_artifact(
    config: HybridConfig, connection: sqlite3.Connection
) -> None:
    actual = metadata(connection)
    if actual.get("dense_embedding_text_recipe") != config.dense_recipe:
        raise ValueError(
            "hybrid config dense recipe does not match the dense artifact"
        )


def validate_frozen_hybrid_config(
    config: HybridConfig, config_digest: str | None
) -> None:
    is_frozen_config = config.frozen
    has_committed_digest = config_digest == FROZEN_HYBRID_CONFIG_SHA256
    if not is_frozen_config or not has_committed_digest:
        raise ValueError(
            "holdout comparison requires the committed frozen hybrid config"
        )


def run(args: argparse.Namespace) -> dict[str, Any]:
    validate_retriever_split(args.retriever, args.split)
    is_holdout = args.split == "holdout"
    holdout_access_granted = getattr(args, "allow_holdout", False)
    if is_holdout and not holdout_access_granted:
        raise ValueError("holdout labels require --allow-holdout")
    hybrid_config = None
    hybrid_candidate = None
    hybrid_config_digest = None
    if args.retriever == "hybrid":
        hybrid_config_path = getattr(args, "hybrid_config", None)
        if hybrid_config_path is None:
            raise ValueError("hybrid retrieval requires --hybrid-config")
        hybrid_config = load_hybrid_config(hybrid_config_path)
        hybrid_config_digest = sha256_file(hybrid_config_path)
        requested_candidate_id = getattr(args, "hybrid_candidate", None)
        if requested_candidate_id is None:
            hybrid_candidate = hybrid_config.selected
        else:
            is_unselected_holdout_candidate = (
                is_holdout
                and requested_candidate_id != hybrid_config.selected_candidate_id
            )
            if is_unselected_holdout_candidate:
                raise ValueError(
                    "holdout comparison must use the selected frozen hybrid candidate"
                )
            hybrid_candidate = next(
                (
                    candidate
                    for candidate in hybrid_config.candidates
                    if candidate.candidate_id == requested_candidate_id
                ),
                None,
            )
            if hybrid_candidate is None:
                raise ValueError(
                    f"unknown hybrid candidate: {requested_candidate_id}"
                )
        if is_holdout:
            validate_frozen_hybrid_config(hybrid_config, hybrid_config_digest)
    else:
        has_hybrid_config = getattr(args, "hybrid_config", None) is not None
        has_hybrid_candidate = getattr(args, "hybrid_candidate", None) is not None
        if has_hybrid_config or has_hybrid_candidate:
            raise ValueError(
                "--hybrid-config and --hybrid-candidate are only valid with --retriever hybrid"
            )
    dataset_path = Path(args.dataset)
    dataset = load_json(dataset_path)
    validate_dataset(dataset, args.split)
    if hybrid_config is not None:
        validate_hybrid_config_for_dataset(hybrid_config, dataset)
    tasks = [task for task in dataset["tasks"] if task["split"] == args.split]
    dense_client = None
    baseline_query_times_ms: list[float] = []
    keyword_query_times_ms: list[float] = []
    try:
        with sqlite3.connect(args.artifact) as connection:
            frozen_artifact = validate_artifact(
                connection,
                dataset,
                Path(args.manifest) if args.manifest else None,
            )
            if hybrid_config is not None:
                validate_hybrid_config_for_artifact(hybrid_config, connection)
            validate_labels(connection, tasks)
            uses_dense = args.retriever in {"dense", "hybrid"}
            if uses_dense:
                has_missing_dense_arguments = (
                    args.dense_helper is None or args.model_cache is None
                )
                if has_missing_dense_arguments:
                    raise ValueError(
                        f"{args.retriever} retrieval requires --dense-helper and --model-cache; "
                        "the semantic path has no keyword fallback"
                    )
                dense_client = DenseClient(
                    args.dense_helper, args.artifact, args.model_cache
                )
            results = []
            for task in tasks:
                started = time.perf_counter()
                if args.retriever == "dense":
                    candidates = dense_client.query(task["question"], task["platform"])
                elif args.retriever == "hybrid":
                    keyword_started = time.perf_counter()
                    keyword_candidates = fetch_candidates(
                        connection,
                        task["question"],
                        task["platform"],
                        hybrid_candidate.keyword_budget,
                    )
                    keyword_query_times_ms.append(
                        (time.perf_counter() - keyword_started) * 1000
                    )
                    dense_candidates = dense_client.query(
                        task["question"],
                        task["platform"],
                        hybrid_candidate.dense_budget,
                    )
                    candidates = fuse_candidates(
                        keyword_candidates, dense_candidates, hybrid_candidate
                    )
                else:
                    candidates = fetch_candidates(
                        connection, task["question"], task["platform"]
                    )
                if args.retriever in {"keyword", "dense"}:
                    displayed = plain_results(candidates)
                elif args.retriever == "hybrid":
                    displayed = hybrid_results(candidates, hybrid_candidate)
                else:
                    displayed = current_adapter_results(candidates)
                if args.retriever in {"keyword", "current-adapter"}:
                    baseline_query_times_ms.append(
                        (time.perf_counter() - started) * 1000
                    )
                results.append(score_task(task, displayed, candidates))
    finally:
        if dense_client is not None:
            resources = dense_client.resources()
            if args.retriever == "hybrid":
                resources["keyword"] = query_resources(keyword_query_times_ms)
            dense_client.close()
        else:
            resources = baseline_resources(baseline_query_times_ms)
    report = {
        "dataset_id": dataset["dataset_id"],
        "dataset_schema_version": dataset["schema_version"],
        "scorer_version": dataset["scorer_version"],
        "split_id": dataset["split_id"],
        "split": args.split,
        "retriever": args.retriever,
        "retriever_version": {
            "keyword": KEYWORD_RETRIEVER_VERSION,
            "current-adapter": CURRENT_ADAPTER_VERSION,
            "dense": DENSE_RETRIEVER_VERSION,
            "hybrid": HYBRID_RETRIEVER_VERSION,
        }[args.retriever],
        "corpus": frozen_artifact,
        "resources": resources,
        "hybrid": (
            {
                "config_id": hybrid_config.config_id,
                "config_sha256": hybrid_config_digest,
                "config_frozen": hybrid_config.frozen,
                "config_frozen_at": hybrid_config.frozen_at,
                "dataset_id": hybrid_config.dataset_id,
                "split_id": hybrid_config.split_id,
                "corpus": hybrid_config.corpus,
                "dense_recipe": hybrid_config.dense_recipe,
                "corpus_policy": hybrid_config.corpus_policy,
                "reference_policy": hybrid_config.reference_policy,
                "retriever_versions": hybrid_config.retriever_versions,
                "metrics": list(hybrid_config.metrics),
                "selection_rule": hybrid_config.selection_rule,
                "development_selected_candidate_id": select_development_candidate(
                    hybrid_config
                ),
                "development_results": hybrid_config.development_results,
                "candidate": hybrid_candidate_report(hybrid_candidate),
            }
            if hybrid_config is not None
            else None
        ),
        "historical_policy_smoke": "separate: scripts/smoke_offline.sh",
        "holdout_access": {
            "authorized": not is_holdout or holdout_access_granted,
            "recorded": is_holdout,
            "utc": datetime.now(timezone.utc).isoformat() if is_holdout else None,
        },
        "summary": summarize(tasks, results),
        "tasks": results,
    }
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--artifact", required=True, type=Path)
    result.add_argument("--dataset", required=True, type=Path)
    result.add_argument("--manifest", type=Path)
    result.add_argument("--split", choices=("dev", "holdout"), default="dev")
    result.add_argument("--allow-holdout", action="store_true")
    result.add_argument(
        "--retriever",
        choices=("keyword", "current-adapter", "dense", "hybrid"),
        default="keyword",
    )
    result.add_argument(
        "--dense-helper",
        type=Path,
        help="Path to the provisioned tldr_subset binary for dense retrieval",
    )
    result.add_argument(
        "--model-cache",
        type=Path,
        help="Offline fastembed cache containing the pinned MiniLM snapshot",
    )
    result.add_argument(
        "--hybrid-config",
        type=Path,
        help="Frozen development/holdout configuration for hybrid retrieval",
    )
    result.add_argument(
        "--hybrid-candidate",
        help="Development-only candidate ID from --hybrid-config for bounded tuning",
    )
    result.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run(args)
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(encoded, encoding="utf-8")
        else:
            print(encoded, end="")
    except (
        AttributeError,
        KeyError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        TypeError,
        ValueError,
    ) as error:
        print(f"evaluation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
