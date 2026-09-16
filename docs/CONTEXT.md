# Askman Retrieval Context

This glossary defines the product language for the Better Askman work. Release and evaluation policy lives in the ADRs.

**Askman**:
An offline CLI that maps natural-language terminal tasks to command examples.
_Avoid_: command executor, assistant

**Main**:
The currently shipped Askman behavior used as the comparison baseline.
_Avoid_: actual version

**Retrieval-v2**:
The candidate retrieval path.
_Avoid_: finished release

**Better Askman**:
An Askman release that improves on `main` without required regressions.

**Evaluation task**:
A labeled natural-language request used to judge whether Askman displays an acceptable command example or correctly abstains.

**Regression benchmark**:
The `evaluation-v1` task set for detecting accidental changes.

**Release benchmark**:
The `evaluation-v2` task set for comparing `retrieval-v2` with `main`.

**Success@1**:
The percentage of answerable tasks whose first displayed example is acceptable.

**Success@3**:
The percentage of answerable tasks with at least one acceptable example among the first three displayed results.

**Scenario family**:
A group of related evaluation tasks.

**Answerable task**:
An evaluation task for which the selected corpus contains an acceptable command example for the requested platform.

**Unanswerable task**:
An evaluation task for which the selected corpus and platform contain no acceptable command example.

**Acceptable example**:
A corpus example whose demonstrated behavior fully satisfies an answerable task for its requested platform.

**Incorrect answer**:
A result that fails an answerable task.

**False answer**:
A result returned for an unanswerable task.

**Paired comparison**:
A comparison of `main` and `retrieval-v2` on the same evaluation tasks and conditions.

**User-visible result**:
The command examples or abstention shown by Askman.

**Hybrid retrieval**:
A retrieval path combining lexical and dense candidate retrieval before producing one final ordered result set.

**Rank fusion**:
The combination of independent retrieval rankings into one ordered result set.

**Abstention**:
The deliberate `No good matches found.` outcome when no candidate clears the confidence policy.

**Matching bundle**:
Versioned offline assets used by a compatible Askman release.

**Explicit update**:
A deliberate user-requested change to the active matching bundle.

**Active bundle**:
The matching bundle used for current queries.

**Rollback**:
Restoring a previous valid release state.

**Release version**:
The identifier for a published Askman release.

**Benchmark provenance**:
The origin and traceability of benchmark tasks.

**Pareto improvement**:
An improvement in primary usefulness without required regressions.
