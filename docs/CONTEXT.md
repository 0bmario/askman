# Askman Retrieval Context

This glossary defines the product language for the Better Askman work. Release and evaluation policy lives in the ADRs.

**Askman**:
An offline CLI that maps natural-language terminal tasks to command examples.
_Avoid_: command executor, assistant

**Main**:
The currently shipped Askman behavior used as the comparison baseline.
_Avoid_: actual version

**Retrieval-v2**:
The candidate retrieval path intended to become the improved shipped version after it passes the release gate.
_Avoid_: finished release

**Better Askman**:
A shipped Askman version that is a measured improvement over `main` without safety, platform, offline, or operational regressions.

**Evaluation task**:
A labeled natural-language request used to judge whether Askman displays an acceptable command example or correctly abstains.

**Regression benchmark**:
The immutable `evaluation-v1` task set used to detect accidental changes during retrieval work.

**Release benchmark**:
The `evaluation-v2` task set used to compare `retrieval-v2` with `main`; its policy is defined in ADR 0002.

**Success@1**:
The percentage of answerable tasks whose first displayed example is acceptable.

**Success@3**:
The percentage of answerable tasks with at least one acceptable example among the first three displayed results.

**Scenario family**:
A group of related evaluation tasks representing one intent pattern for per-family comparison.

**Answerable task**:
An evaluation task for which the selected corpus contains an acceptable command example for the requested platform.

**Unanswerable task**:
An evaluation task for which the selected corpus and platform contain no acceptable command example.

**Acceptable example**:
A corpus example whose demonstrated behavior fully satisfies an answerable task for its requested platform.

**Incorrect answer**:
A displayed result that does not satisfy an answerable task.

**False answer**:
A non-empty result for an evaluation task labeled unanswerable.

**Paired comparison**:
An evaluation of `main` and `retrieval-v2` using identical task inputs, target-platform flags, corpus or matching bundle, model and other assets, runtime conditions, and network policy.

**User-visible result**:
The command examples and abstentions printed by the Askman CLI; internal retrieval metrics are diagnostics.

**Hybrid retrieval**:
A retrieval path combining lexical and dense candidate retrieval before producing one final ordered result set.

**Rank fusion**:
The lightweight combination of independent retrieval rankings used by hybrid retrieval; it is not a learned second-stage reranker.

**Diagnostic retrieval modes**:
Keyword-only and dense-only paths used to investigate retrieval behavior, not permanent user-selectable modes.

**Abstention**:
The deliberate `No good matches found.` outcome when no candidate clears the confidence policy.

**Matching bundle**:
The versioned offline corpus, retrieval indexes, and embedding model required by a compatible Askman release.

**Explicit update**:
A deliberate user-requested change to the active matching bundle; normal searches do not update assets.

**Active bundle**:
The validated matching bundle selected for current queries.

**Rollback**:
Restoring a previously valid compatible release state after an update fails or is rejected.

**Package distribution**:
The Askman CLI is published to crates.io and compatible matching bundles are published as GitHub Release assets.

**Release version**:
The first Better Askman release is `0.4.0`.

**Benchmark provenance**:
Release tasks are authored from public, license-compatible user intents before retrieval outputs are inspected, then labeled against the pinned corpus with stable IDs and rationales; private data and copied candidate answers are excluded.

**Pareto improvement**:
An improvement in primary usefulness without regression in safety, platform coverage, offline behavior, or agreed operational limits.
