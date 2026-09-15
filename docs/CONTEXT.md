# Askman Retrieval Context

This context defines the user-facing retrieval product and the evidence required to promote `retrieval-v2` into the improved Askman release.

Status: agreed target behavior for Better Askman `0.4.0`. The release benchmark, bundle lifecycle, distribution, and verification requirements below are planned; this document does not claim they are implemented or the release gate has passed. Existing implementation evidence lives in [reproducibility](reproducibility/heldout-evidence.md).

## Product language

**Askman**:
An offline CLI that maps natural-language terminal tasks to command examples.
_Avoid_: command executor, assistant

**Main**:
The currently shipped Askman behavior used as the comparison baseline.
_Avoid_: actual version

**Retrieval-v2**:
The next candidate retrieval path for Askman, intended to become the improved shipped version after it passes the agreed release gate.
_Avoid_: research branch, finished release

**Better Askman**:
A shipped Askman version that is a Pareto improvement over `main`: it improves paired top-result usefulness across multiple scenario families, introduces no safety or platform regressions, stays within the agreed operational budget, and has reproducible evidence.
_Avoid_: nicer project, more robust by intuition

**Evaluation task**:
A labeled natural-language request used to judge whether Askman displays an acceptable command example or correctly abstains.

**Regression benchmark**:
The immutable `evaluation-v1` task set used to detect accidental changes while retrieval work proceeds.

**Release benchmark**:
The new `evaluation-v2` task set used to decide whether `retrieval-v2` is better than `main`; it contains 120 new, balanced, cross-platform tasks with a hidden holdout.

**Answerable task**:
An evaluation task for which the selected corpus contains at least one command example that satisfies the requested behavior on the requested platform.

**Unanswerable task**:
An evaluation task for which the selected corpus and platform contain no acceptable command example.

**Acceptable example**:
A corpus example whose demonstrated behavior fully satisfies an answerable task for its requested platform.

**Paired comparison**:
An evaluation of `main` and `retrieval-v2` on the same task, corpus, platform policy, and run conditions.

**User-visible result**:
The command examples and abstentions printed by the Askman CLI; these are the release benchmark's primary evidence, while internal retrieval metrics are diagnostics.

**Release rollout**:
The baseline remains available as a comparison build while `retrieval-v2` is evaluated; once the release gate passes, `retrieval-v2` becomes the default Askman path without shipping two permanent retrieval modes.

**Operational budget**:
The paired comparison permits at most 20% regression in warmed-query p95 and peak memory, reports cold-start p95 separately, and requires no query-time network access.

**Platform validation**:
The release benchmark exercises `common`, `linux`, `osx`, and `windows` through target selection; native smoke checks and a separate CI matrix establish runtime compatibility on actual operating systems.

**Benchmark provenance**:
Release tasks are authored from user intents before candidate results are inspected, then independently labeled against the pinned corpus with stable example IDs and rationales; adversarial synthetic tasks are identified as such.

**Hybrid retrieval**:
The Better Askman retrieval path that combines lexical and dense candidate rankings, then uses rank fusion to produce one final ordered result set.

**Rank fusion**:
The lightweight combination of independent lexical and dense rankings used by hybrid retrieval; it is not a learned second-stage reranker.

**Abstention**:
The deliberate `No good matches found.` outcome when no candidate clears the confidence policy; it is a successful result for an unanswerable task.

**Matching bundle**:
The single immutable, hash-verified cross-platform release set containing the versioned corpus, retrieval indexes, and embedding model required for offline queries.

**Explicit update**:
A deliberate user-requested change to the matching bundle; normal queries never update or mix bundle versions.

**Bundle manifest**:
The release metadata that identifies every matching-bundle component, its version, size, and SHA-256 digest; validation failure prevents activation.

**Active bundle**:
The one validated matching bundle selected for current queries; activation changes only after complete validation succeeds.

**Rollback**:
Restoring the previous valid active bundle when a new bundle cannot be validated or does not work.

**Update command**:
The explicit networked operation that discovers, validates, and atomically activates a newer compatible matching bundle; ordinary searches do not perform this work.

**Package distribution**:
The Askman CLI is published to crates.io, while its compatible matching bundle is published as a hash-verified GitHub Release asset; neither artifact silently substitutes for the other.

**Release verification**:
Every change passes regression and offline checks; a release candidate additionally passes the release benchmark, native platform matrix, bundle verification, and clean-install smoke before the compatible CLI and bundle are published.

**Release version**:
The first Better Askman release is `0.4.0`; its matching bundle records the compatible CLI version and cannot be used with an incompatible version.

**Evidence threshold**:
Retrieval-v2 is better only with at least a five-point absolute `Success@1` gain across two or more scenario families, no family regression, a paired 95% confidence interval supporting a positive gain, and every safety, offline, platform, and operational gate passing; otherwise the result is inconclusive.

**Production corpus**:
The release bundle is built from a complete pinned `tldr-pages` snapshot, filtered only by documented parser rules that remove non-operational reference pages.

**Corpus refresh**:
A new production corpus is created only during an explicit release, with its source commit, parser version, digest, indexes, and benchmark results recorded together.

**Bundle failure**:
An absent, partial, mixed, or invalid matching bundle cannot serve queries; a previous valid active bundle remains untouched. If no valid active bundle is available, Askman exits non-zero with an actionable error.

**Evaluation split**:
`evaluation-v2` has 60 development and 60 hidden holdout tasks, balanced by answerability, platform, and intent family; complete paraphrase families stay within one split, and the retrieval configuration is frozen before holdout scoring.

**Paired evidence**:
Release comparisons report task-level `retrieval-v2` versus `main` outcomes, a fixed-seed 10,000-resample paired bootstrap with a 95% interval, exact per-family counts, and operational measurements.

**Benchmark provenance record**:
Each release task keeps a public, license-compatible source category and normalized intent record, without private user data or copied benchmark answers; raw prompts are fixed before retrieval outputs are inspected.

**False answer**:
A non-empty result for an evaluation task explicitly labeled unanswerable.

**Pareto improvement**:
An improvement in primary usefulness without regression in safety, platform coverage, robustness, or agreed operational limits.
