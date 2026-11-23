# Retrieval-v2 approach review and decision — 2026-09-26

Review starts from working tree `f61e3af`; the latest development candidate is
commit `ba74692`, against main baseline `8bd9fa2` and installed Askman 0.3.3.
Historical v2 evidence includes two dev-only paired gates and one authorized
canonical run; the broad candidate failed its independent holdout. The smaller
candidate was selected on dev only. It was later scored once against fresh
holdout v1 with explicit authorization; the independent gate was inconclusive
and the candidate is not approved. It was later scored once on fresh holdout
v2 after explicit user authorization; that independent gate was also
inconclusive. Neither consumed holdout was used for tuning.

## Recommendation

Keep shipped Askman as the product baseline. The latest development candidate
adds two narrow source-backed query rewrites to the main-compatible dense
path: file-extension search and Windows moves across distinct drives. On the
new dev extension cohort, the canonical CLI gate measured 22/30 vs main 13/30
Success@1 and 27/30 vs 21/30 Success@3, with false answers tied at 0/30. The
original dev cohort measured 28/30 vs 18/30 Success@1 and 30/30 vs 23/30
Success@3, with false answers tied at 1/30. These are development results;
the extension cohort selected the new rules, and the original cohort has
already been used in candidate work. One authorized independent holdout run
improved Success@1 and Success@3 but failed common-platform and family
guardrails; the candidate is not releasable. RRF remains out because controlled
ablations showed no additional value.

A later one-factor hard check of requested actions and constraints against
retrieved examples reduced false answers on new dev data but regressed
Success@1, Success@3, and coverage. Reject that filter too; it is not part of
the development candidate. The latest independent result still applies only
to the query-rewrite candidate, and shipped main remains the product choice.

## Earlier focused candidate — dev only

On the identical 60-task dev split and 142 pinned records, the focused
candidate measured 30/30 Success@1, 30/30 Success@3, and 0/30 false answers;
main measured 18/30, 23/30, and 1/30. Platform Success@1 was common 9/10→10/10,
Linux 7/10→10/10, macOS 1/5→5/5, and Windows 1/5→5/5. Top-three usefulness
improved or tied on all platforms. Network-denied CLI runs had no failures.
Latest main/candidate warm p95 was 86.343/85.001 ms; peak memory was
236,077,752/236,536,504 B. Fresh-process p95 was 89.266/85.653 ms; peak
memory was 236,438,200/282,936,040 B (19.7% higher for candidate). Every
measured phase stayed within the 20% ceiling. The machine decision is
inconclusive because this is dev-only evidence; earlier focused runs remain
for timing context.

Representation, same-page example retrieval, rank blending, cutoff, and fusion
were isolated on dev. Focused and broad query rules tied at 30/30; the focused
rule set is smaller. Hybrid tied dense. Late per-example page selection
regressed top-three usefulness. See the
[`focused controlled ablation`](reproducibility/artifacts/retrieval-v2-controlled-ablation-dev-v2.json)
and
[`latest focused paired dev-only gate`](reproducibility/artifacts/main-vs-retrieval-v2-focused-dev-only-v5.json)
and the
[`previous focused paired dev-only gate`](reproducibility/artifacts/main-vs-retrieval-v2-focused-dev-only-v4.json).
The earlier v3 run remains recorded at
[`main-vs-retrieval-v2-focused-dev-only-v3.json`](reproducibility/artifacts/main-vs-retrieval-v2-focused-dev-only-v3.json).

The candidate is commit `3494a11`; source digest
`ac58a8c3c63390b31f0af599be4939be49e87510e28282be6d8a6c276164dfa2`; binary
digest `2e03c4d99601b9d14f1dc0ad63545c12b274ddc5356abbaa043d8b914ce80521`.
Fresh holdout dataset digest is
`7fe11e153b64941c91233b756543487ebdd34e17bcca7b935a55f8f16a6fb2a0`; freeze
manifest digest `7463ccb782cf971b4893f369c899f408212306020c68e471b72c146b2da68f1a`.
It was scored once against candidate commit
`3494a11c57c31045bb9897c9fa187d768e18ebcb`.

## Authorized focused-candidate holdout result

Main and candidate measured holdout `Success@1` 13/30 vs 15/30, `Success@3`
19/30 vs 15/30, incorrect answered tasks 7/26 vs 10/25, and false answers
13/30 vs 8/30. The observed `Success@1` gain was 6.7 points, but the one-sided
95% paired-bootstrap lower bound was −3.3 points. Linux and Windows regressed
on `Success@3`; incorrect answered tasks regressed overall and on both
platforms. Offline execution had zero failures; latency and memory stayed
within the 20% limits. The canonical decision is inconclusive. Keep shipped
Askman as the product baseline.

The holdout was not used for tuning and is now consumed. Its frozen JSON and
manifest remain unchanged. Do not inspect individual outcomes for candidate
changes. Preserve the complete gate evidence at
[`main-vs-retrieval-v2-focused-fresh-holdout-v1.json`](reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v1.json)
and
[`rendered report`](reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v1.md).

## Authorized lexical-candidate holdout v2 result

Candidate ba74692cf79fa9c294f685fbade8f9315aeacdd1 was scored once after
explicit authorization against the frozen v2 holdout and the identical pinned
142-record corpus. On the default dev split, Success@1 improved 18/30 to 28/30
and Success@3 23/30 to 30/30. On the independent holdout, Success@1 improved
12/30 to 15/30 and Success@3 13/30 to 17/30. Holdout incorrect answered tasks
fell 9/22 to 3/20; false answers tied at 5/30.

The independent one-sided 95% paired-bootstrap lower bound was 0.0, and
common-platform Success@3 fell 4/7 to 3/7. The combined gate also found one
negative Success@1 family. The release decision is inconclusive, so main
remains shipped. Network-denied execution had no failures; measured p95
latency and peak memory stayed within 20% of main. The readiness validator
recognizes the v2 frozen inputs and rejects promotion because the independent
gate conditions do not pass. Do not tune from this consumed holdout. Its
dataset and manifest were not changed. The full result is
[main-vs-retrieval-v2-focused-fresh-holdout-v2.json](reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v2.json)
with its
[rendered report](reproducibility/artifacts/main-vs-retrieval-v2-focused-fresh-holdout-v2.md).

## Earlier broad-candidate matched-corpus results

The canonical gate built the parser-v3 reference corpus from the frozen
manifest, compared it to the v4 candidate, and matched all 142 stable example
IDs plus visible page/example fields (`0a874b…cee1db`). The frozen manifest and
dev dataset were not modified. The new versioned builder input is
[`manifest-v4.json`](../tests/fixtures/tldr-evaluation-v2/manifest-v4.json).

| Paired CLI result on frozen dev | Main | Dense candidate |
| --- | ---: | ---: |
| Success@1, answerable | 18/30 | 30/30 |
| Success@3, answerable | 23/30 | 30/30 |
| False answers, unanswerable | 1/30 | 0/30 |
| Fresh-process p95 | 90.30 ms | 89.79 ms |
| Fresh-process peak memory | 238.2 MB | 245.3 MB |
| Warmed-query p95 | 88.38 ms | 92.39 ms |
| Warmed-query peak memory | 237.5 MB | 236.8 MB |

There were no execution failures. The candidate improved Success@1 in five of
six answerable scenario families and tied the sixth. Platform Success@1 was
common 9/10→10/10, Linux 7/10→10/10, macOS 1/5→5/5, and Windows 1/5→5/5. The
paired dev-only gate result remains `inconclusive` because it used dev tasks
only. In that run fresh p95 was 0.6% faster, fresh peak memory was 3.0% higher,
warmed p95 was 4.5% slower, and warmed peak memory was 0.3% lower. All resource
measurements were within the gate's 20% warmed-query limits. The earlier v1
run measured a 19.9% fresh-memory increase and 2.0% faster warmed p95, showing
material run-to-run variance. Keep both reports; do not select the more
favorable timing. The current source digest is
`419c2a86c559735bd62173885371bd78e67e4c4c8414eef01f05917813bf046d`; the
candidate binary digest remains
`bf3e293d6ecfee8f5d0bbbaafaac57b7498a8fc92adcb8865120b89ff6a077d9`.

## Authorized paired evaluation

The canonical run used the exact pinned main database
(`ef3b96cc…819db`), frozen candidate bundle
(`matching-bundle-v2:8e537945…191e4`), 142 equivalent parser-v3/v4 records,
and network-denied queries. Main and candidate had zero execution failures.

| Split | Metric | Main | Candidate |
| --- | --- | ---: | ---: |
| Dev | Success@1 / Success@3 | 18/30 / 23/30 | 30/30 / 30/30 |
| Dev | False answers | 1/30 | 0/30 |
| Holdout | Success@1 / Success@3 | 19/30 / 25/30 | 19/30 / 20/30 |
| Holdout | False answers | 6/30 | 6/30 |
| Combined | Success@1 / Success@3 | 37/60 / 48/60 | 49/60 / 50/60 |

Holdout first-result accuracy tied; top-three usefulness dropped by five tasks.
Holdout Success@3 regressed on macOS (10/10 to 8/10) and Windows (4/5 to
1/5). The runner reports `better_askman` because its pooled bootstrap is
dominated by dev gains. Under the requested independent no-regression
conditions this is a no-go. The full immutable report is
[`authorized paired gate`](reproducibility/artifacts/main-vs-retrieval-v2-authorized-v1.json).

Warmed p95 improved from 91.64 ms to 88.56 ms; peak memory increased from
237,175,480 to 237,535,904 bytes. Both stay within the 20% bounds. Offline
operation, first-result platform behavior, and holdout false-answer rate did
not regress; relevance is the blocker. The holdout is consumed and cannot be
used to tune another candidate.

The rebuilt v4 bundle parsed all 24 selected source files. It contains 142
examples, with 139 in both dense and FTS indexes. The three unindexed records
are `tldr` navigation commands; all other examples are indexed. Each stored
embedding text exactly matches the pinned main importer's template; vectors
are 384-dimensional and L2-normalized. The v3 reference rebuild matches all
142 candidate example IDs and visible records.

Controlled ablations isolated the selected factors on the same 60 dev tasks:

- Raw dense with main-compatible text and cutoff: 20/30 Success@1, 24/30
  Success@3, 0/30 false answers.
- Adding `IntentRulesV1`: 30/30 Success@1, 30/30 Success@3, 0/30 false
  answers.
- Hybrid with the same expansion and guard: identical 30/30, 30/30, 0/30.
- Raw hybrid and raw dense tied at 20/30, 24/30, 0/30 false answers.
- Late per-example page selection kept Success@1 at 20/30 but dropped
  Success@3 from 24/30 to 20/30.
- Raw dense cutoff sweep: 0.45 gave 12/30 Success@1; 0.50 gave 17/30; 0.55
  gave 20/30 with no false answers; 0.60 added one false answer without a
  Success@1 gain.

The query-helper p95 was 7.8 ms for expanded dense queries versus 5.8 ms raw;
helper peak memory was 300.6 MB expanded versus 287.9 MB raw. Full CLI timings
and memory above are the gate measurements. The selected candidate stayed
within the gate's 20% latency/memory bounds.

Reproducible raw reports:
[controlled ablations](reproducibility/artifacts/retrieval-v2-controlled-ablation-dev-v1.json),
[latest paired dev-only gate](reproducibility/artifacts/main-vs-retrieval-v2-dev-only-v2.json),
[earlier paired dev-only gate](reproducibility/artifacts/main-vs-retrieval-v2-dev-only-v1.json).

## Actual installed-product sample

The installed `/Users/mmo/.local/bin/askman` is version 0.3.3 with binary
SHA-256 `723e8720cd53759769ca3f0a399dc99b9b954920941608fdbee227ff3f711078`.
Its tagged source resolves the macOS default data path to
`~/Library/Application Support/askman`; that database is the official
v0.3.3 artifact (`0218c1fd…5f71495`). A separate `.local/share` database has a
different hash and is not used by this binary. Network-denied queries against
the actual installed path returned useful `cp` for “copy files” and `cb` for
“copy text to clipboard”. They also reproduced three failures: “restart a
Linux service” returned `needrestart` (check daemons after library upgrades),
macOS DNS-cache flush returned Debian `resolvconf`, and Windows event-log view
returned `eventcreate` (create an event) before a second event-source example.
This product sample uses a different corpus from the 142-example gate set, so
it cannot be scored against those frozen labels. The exact query outputs and
binary/database hashes are captured in the
[`installed v0.3.3 sample`](reproducibility/artifacts/installed-v0.3.3-smoke-v1.json).

A fresh read-only inventory of the actual installed database confirmed the
hash from
[`offline-smoke.md`](reproducibility/offline-smoke.md):
`0218c1fd18dc6eb1c6b405356c92e47379286cec68f9fea1a70be896d5f71495`. It has
30,205 vector rows, 6,775 distinct commands, and four platform labels. Counts
are common 20,245 rows / 4,464 commands, Linux 7,917 / 1,825, macOS 946 / 358,
and Windows 1,097 / 260. Every row has a non-empty command, example
description, and example command; 5,943 command/platform groups contain
multiple examples, with one duplicate example group. Eight rows use the
`tldr` navigation command. These are stored-database coverage counts, not a
full-source parsing-recall audit; the release database does not record its
source revision. Reproduce the stored-row inventory with
`cargo run --locked --offline --example audit_installed_db -- <commands.db>`;
the helper opens the supplied database read-only.

Main already uses `AllMiniLML6V2` ONNX embeddings and SQLite vector KNN. Earlier
claims that main is lexical-only were wrong. The historical `current-adapter`
is a lexical surrogate with main's heuristics, not the shipped main CLI.

## Evidence and its limits

| Evidence | Observation | What it establishes |
| --- | --- | --- |
| Initial five-example fixture | Keyword 13/13 S@1; dense 12/13; guarded hybrid 13/13. Unguarded dense answered all 17 negatives incorrectly. | Reproducibility and need for abstention; no hybrid quality advantage. |
| Expanded 24-page dev corpus | Keyword 1/30 S@1; dense description 18/30; guarded hybrid 19/30, zero false answers. | Strict lexical matching fails on paraphrases; guard improves selectivity. Does not isolate fusion from filtering. |
| Query expansion on same dev set | Hybrid S@1 19/30 → 23/30 → 26/30; S@3 reaches 30/30; zero false answers. | Representation/order changes help this development set. Same prompts were used for tuning. |
| Historical paired release gate (earlier candidate) | Main/v2 S@1 37/60 → 45/60; S@3 48/60 → 52/60; false answers 7/60 → 0/60. Verdict inconclusive. | Earlier candidate only; it failed a family guard and memory budget. Do not transfer this result to the current candidate. |
| Initial full-corpus heuristic | Different installed/candidate corpora; main 7 hits, v2 6. | User-facing failure discovery; cannot attribute differences to retrieval. |
| Controlled canonical-record intersection | Main wins 7 cases, v2 4, ties 9 under broad manual rubric; mean one-shot times about 94 ms / 179 ms. | Description-only v2 can lose even with matched visible records. Synthetic corpus and restricted main intersection limit product conclusions. |
| Later strict manual audit | Main 5/17 S@1, 7/17 S@3; pre-fix v2 10/17, 12/17. Subsequent conversation reports v2 13/17 at both ranks after targeted fixes. | Improvement on an inspected development sample. Latest score was not independently reproduced in this review; not a fresh test set. |
| Historical full source/import audit | Main 32,239 rows; v2 32,173 stored examples, 31,400 indexed operational examples; 57 excluded pages. | Recorded historical counts, not rebuilt in this run. A shared source revision alone does not prove equivalent retrieval corpora. |
| KNN and startup investigations | Partitioned KNN, bounded `k`, exact fallback, named-model initialization, validation reuse implemented. | Reliability work alone does not prove relevance. The current dev-only gate now measures fresh and warmed CLI latency; it does not establish performance on the full installed corpus. |
| Parser-v3/v4 record audit | Rebuilt v3 from its frozen manifest and compared to v4: 142/142 IDs and visible records equal; current fixture has 139 operational rows after excluding three navigation examples. | Candidate labels remain relative to the same records; this is not evidence about the full tldr corpus. |
| Paired canonical dev-only gate (pre-authorized run) | Main 18/30 S@1, 23/30 S@3, 1/30 false; candidate 30/30, 30/30, 0/30. No execution failures; resource limits pass. | Exact pinned-record development comparison; not independent validation. |
| Earlier broad-rule controlled ablation | Main-compatible text + `IntentRulesV1` reached 30/30 S@1 and S@3; hybrid tied it. Dense-only without expansion was 20/30 S@1. | Expansion benefit did not validate on its consumed holdout. The focused candidate's later independent result is recorded above. |

Checked-in historical sources:
[dense](reproducibility/dense-retrieval.md),
[hybrid](reproducibility/hybrid-retrieval.md),
[dev expansion artifact](reproducibility/artifacts/evaluation-v2-expanded-dev-hybrid-query-expansion-v2.json),
[gate record](reproducibility/release-gate.md).

Scratch evidence inspected:
`/private/tmp/askman-same-corpus-audit-e718.json`,
`/private/tmp/askman-same-corpus-e718-final.json`,
`/private/tmp/askman-main-v2-compare.xX5BpT/main-v2-heuristic-final.json`,
`/private/tmp/askman-canonical-main-parity.fQn0rf/experiment2/controlled-20-results.json`,
and its `postbuild-parity.json`.
These paths are ephemeral; preserve validated reports with source/binary/config
digests when creating the next versioned evidence package. The legacy scratch
import report records a runtime teardown failure; its derivative experiments
are exploratory, not clean release inputs.

## ADR review

| ADR | Assessment | Proposed treatment |
| --- | --- | --- |
| 0001 — release gate | The original pooled decision could hide holdout regression. | Split-specific conditions correctly leave the focused candidate inconclusive. |
| 0002 — benchmarks | Corpus-relative labels and split separation remain useful; both prior holdouts are consumed. | Preserve fresh-holdout-v1; any future holdout must be unseen and explicitly authorized before scoring. |
| 0003 — hybrid | Fusion added no value; both broad and focused dense candidates failed independent review. | Keep focused dense-only for development; do not promote or tune from consumed holdouts. |
| 0004 — bundles | Appropriate for offline reproducibility, compatible assets, explicit updates, atomic activation, and rollback. | Retained. Candidate bundle keeps lexical index for evaluation/identity checks; its experimental CLI path uses dense-only retrieval. |
| 0005 — distribution | Appropriate; separate source/model assets from executable distribution. It does not establish retrieval quality. | Retain; apply only after quality/runtime evidence and reproducible production inputs pass. |

Historical hybrid documentation contains contradictory shipping/raw versus
expanded-query statements. Replace the current-behavior section after the
design decision; preserve historical experiments as dated records.

## Corpus and database design

TLDR is a suitable first corpus: concise source-backed task/example pairs,
platform metadata, command syntax, license, offline availability. SQLite is
suitable storage for this corpus. Neither a database engine replacement nor a
new embedding model is supported by current evidence.

Define the retrieval unit as one operational command example. Preserve source
bytes, revision, path, page/example IDs, description, syntax, and platform.
Resolve reference/disambiguation pages to operational destinations; exclude
documentation-navigation examples from task results, with an auditable reason.
Check exclusions for lost operational support, rather than assuming every
parser exclusion is harmless.

Make embedding text a versioned build recipe. Main embeds:
`Task: <example>. Command: <command>. Description: <page>. Example: <example> <syntax>`.
Early v2 embeds only the example description. This removes context and syntax
that distinguish related commands and behavior variants. Current v2 supports
and requires `main-compatible`; existing description-only bundles are
historical inputs and cannot automatically establish current behavior.

Compare main-compatible text with a concise source-derived task/command/page/
syntax representation. Do not add benchmark prompts or generated "acceptable"
answers to the index. Preserve reference URLs as attribution; test any removal
from embedding text as a separate representation change. Text normalization,
command aliases, and descriptions must be recorded, since they affect both
embeddings and main's domain/command preferences.

Audit parser coverage, platform overrides, operational-example counts,
lexical/dense identity equality, vector coverage, and deterministic rebuilds.
For matched retrieval experiments, require equal visible records and selection
policies. Keep each implementation's independently generated vectors; copying
v2 vectors into main would remove the representation difference being tested.

Report two comparisons: actual installed-product behavior, and controlled
retrieval with identical corpus records. The first measures user benefit; the
second identifies why behavior changed.

Corpus limitations matter: a complex request may require combining flags or
commands that no single TLDR example demonstrates. This product retrieves
examples; its current contract does not synthesize new commands. Missing
support is a corpus/product-scope issue, not necessarily a ranking bug.

## Earlier focused retrieval path — historical (2026-09-26)

The product path validates the active immutable bundle and its
main-compatible recipe, embeds the query with `FocusedIntentRulesV1` (five
focused intent rules, six source-backed expansions), and searches common
vectors plus target-platform vectors for non-common targets. Explicit platform
requests prefer a target-specific example on score ties. It page-deduplicates
candidates early, keeps up to eight, applies raw cosine distance `<= 0.55`,
displays up to three, and abstains if none remain. It preserves the negated
EXIF guard, adds scoped abstention for negated file-to-stdout requests, and
abstains when a query excludes `cat`, the pinned corpus's only verified
full-file stdout example. Ordinary positive stdout requests remain eligible;
“without using cat” is treated as a tool exclusion, not negated output.
A direct dev CLI check had exposed `cat` at distance `0.4489` for “do not show
file contents to stdout”; the final build returns “No good matches found.” A
positive “show file contents to stdout” query still returns the pinned `cat`
example first (distance `0.3169`).

The controlled ablation supports that order: late page selection kept
Success@1 at 20/30 but reduced Success@3 from 24/30 to 20/30 for raw dense.
The broad `IntentRulesV1` raised dense-only Success@1 and Success@3 to 30/30;
the smaller `FocusedIntentRulesV1` tied it on dev. Hybrid RRF matched dense-only
on the tested dev configuration, so the selected product path does not load or
fuse lexical candidates. The `0.55` cutoff and intent rules remain dev-derived;
do not treat the cutoff as calibrated confidence or transfer it to another
recipe/corpus without new development evidence.

Retain proven initialization and KNN fixes. A follow-up may break down model
initialization, validation, embedding, vector lookup, and ranking separately;
fresh and warmed full-CLI timings are now recorded. Internal server timings
cannot replace fresh CLI process latency. Avoid adding a daemon, learned
reranker, model replacement, or generic command-semantic ontology before
simpler candidates are tested.

## New dev-only cohort and selected candidate

The original 60-task development split had been repeatedly inspected. A new
cohort was authored and frozen before retrieval runs: 60 tasks, 12 new scenario
families, 30 answerable / 30 unanswerable, and 15 per platform. It uses the
same parser-v4 corpus bundle as the controlled main comparison: 142 visible
examples, source digest
`651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`.
Dataset SHA-256 is
`6c113bed013be3f532a8287c58a4f257347585c2be963d6c3b475d41ecc49905`; freeze
manifest SHA-256 is
`9dcf13de29e6b0969344e6b2c64b298f9550ac320dad67dfca4a8a9ad9a096d5`.
The custom-cohort path is restricted to the canonical runner's `--dev-only`
mode. It does not read holdout rows or make a release decision.

| Candidate | Success@1 | Success@3 | Coverage | Incorrect answered | False answers |
| --- | ---: | ---: | ---: | ---: | ---: |
| Main | 13/30 | 21/30 | 24/60 | 3/24 | 0/30 |
| Focused dense, one/page, 0.55 | 14/30 | 14/30 | 22/60 | 8/22 | 0/30 |
| Focused dense, same-page, 0.55 | 14/30 | 19/30 | 22/60 | 3/22 | 0/30 |
| Focused dense, same-page, 0.60 | 14/30 | 21/30 | 24/60 | 3/24 | 0/30 |
| Broader query rules, same-page, 0.60 | 14/30 | 21/30 | 24/60 | 3/24 | 0/30 |
| Focused + same-page + 0.60 + lexical 0.05 | **15/30** | **22/30** | 24/60 | **2/24** | 0/30 |

The selected variant gives the best development results. Against main, it gains
two first-result tasks (6.7 pp), one top-three task, and reduces incorrect
answered tasks by one. Two families improve and none regress. Per-platform
Success@1 is common 3/10 vs 2/10, Linux 2/5 vs 1/5, macOS 8/10 tie, Windows
2/5 tie. Per-platform Success@3 has no regressions. The one-sided 95% paired
bootstrap lower bound for Success@1 is 0.0 pp, so the canonical gate is
inconclusive. The candidate is still development-only.

Network-denied runs had zero execution failures. Fresh-process p95 latency and
peak memory were 84.511 ms / 256,328,376 B for candidate vs 86.721 ms /
237,028,024 B for main. Warm p95 and peak memory were 84.399 ms / 237,765,328 B
vs 85.258 ms / 235,930,296 B. Both phases stay within the 20% limit. The
candidate source digest is
`f84e6424cdb88b92726819a40737811a57f64c94b383e936e5c05624219e0627`; binary
digest is
`20193571cef751a3d38fd1e12f9d26dd3512fbcc04498d78f128eee906ec3e8f`.

The experiments isolate example selection, abstention cutoff, query mode, and
ranking. Same-page selection improves Success@3 over early one-per-page
selection; 0.60 restores main-level coverage/top-three/safety; broader rules
tie the smaller focused rules. The 0.05 lexical rerank improves on the same
focused/same-page/0.60 baseline. Historical evidence favors main-compatible
embedding text over description-only vectors and found RRF tied with dense
retrieval; the new lexical reranker is not RRF. Keep RRF out. These controlled
results are development evidence, not holdout validation.

Full paired CLI artifacts: [focused baseline](reproducibility/artifacts/main-vs-dev-extension-v1-focused.json), [same-page selection](reproducibility/artifacts/main-vs-dev-extension-v1-same-page.json), [0.60 cutoff](reproducibility/artifacts/main-vs-dev-extension-v1-cutoff-060.json), [broader query rules](reproducibility/artifacts/main-vs-dev-extension-v1-intent-rules-same-page-cutoff-060.json), and [selected lexical candidate](reproducibility/artifacts/main-vs-dev-extension-v1-focused-same-page-cutoff-060-lexical-005.json). Each has a rendered Markdown report beside the JSON.

## Remaining validation

1. Candidate implementation, dev-only paired reports, controlled ablations,
   installed-product sample, and the authorized fresh-holdout report are
   recorded.
2. Candidates `3494a11` and `ba74692` did not pass independent
   validation. Both fresh holdouts are consumed. Do not tune from them. A new
   candidate needs a fresh unseen holdout and explicit authorization before
   scoring. See the [holdout v2 freeze record](reproducibility/fresh-holdout-v2-freeze.md).
3. The exact paired gate uses the 142-record pinned evaluation corpus. The
   installed 0.3.3 database is a different, larger corpus; its sampled behavior
   and stored-row inventory were reported separately. Full-source parsing
   recall for the installed database remains unmeasured.

The previous focused lexical candidate (`ba74692`) improved on both dev
cohorts and holdout v2 but failed the independent bootstrap and no-regression
conditions. Those results did not validate or tune the newer query-rule
candidate. Its independent v3 result is recorded below and also fails release
guardrails. Shipped main remains the product baseline. A passing benchmark
result does not establish improvement on the separately sampled installed-
product corpus.

## Latest query-rule candidate — development selection (2026-09-27)

The source review found pinned operational examples that matched two dev
extension families the focused-v1 candidate missed. Controlled dense ablations
held embedding text, corpus, selection, cutoff, lexical rerank, display limit,
and guards fixed. Extension-only measured 19/30 Success@1 and 24/30 Success@3;
cross-drive-only measured 18/30 and 25/30; the combined mode measured 22/30 and
27/30, with 0/30 false answers for all modes. Focused-v1 measured 15/30,
22/30, and 0/30. The targeted extension family moved from 0/5 to 4/5 Success@1;
the Windows cross-drive family moved from 2/5 to 5/5. Full internal outcomes:
[`focused query rewrite ablation`](reproducibility/artifacts/focused-query-rewrites-dev-extension-v1-native-platform.md).

The exact CLI comparison used the same 142 parser-v4 records as installed main.
On the dev-extension cohort, main/candidate measured Success@1 13/30→22/30,
Success@3 21/30→27/30, coverage 24/60→29/60, incorrect answered 3/24→2/29,
and false answers 0/30→0/30. Success@1/Success@3 improved or tied on every
platform. The paired bootstrap one-sided 95% lower bound was 16.7 pp; the
runner still returns `inconclusive` because this is dev-only data. On the
previously inspected default dev split, main/candidate measured Success@1
18/30→28/30, Success@3 23/30→30/30, and false answers 1/30→1/30. Neither cohort
is independent validation.

Both final gate reruns passed network-denied execution, latency, and memory
conditions. On the custom cohort, fresh p95 was 87.916/87.063 ms and peak
memory 253,461,200/236,339,896 B (candidate/main); warmed p95 was
86.624/89.515 ms and memory 236,536,504/236,798,672 B. On default dev, fresh
p95 was 86.645/86.747 ms and peak memory 283,067,136/236,339,920 B; warmed
p95 was 90.365/86.950 ms and memory 237,732,536/236,470,968 B. Fresh default
memory is 19.8% higher, within the 20% gate limit but with little headroom.
Corpus-record equivalence passed for all 142 records.

An initial candidate restricted the extension rewrite to the abstract
`common` platform. The CLI maps common tasks to the host OS, so that rule did
not fire on macOS. The corrected rule covers Linux/macOS shared-page selection
and excludes Windows. The first gate artifact remains preserved as an
exploratory scope check:
[`initial platform scope`](reproducibility/artifacts/main-vs-dev-extension-v1-focused-v2-query-rules.md).

Before the authorized v3 run, this candidate had not been scored on a holdout;
the v1 and v2 outcomes were not used to choose these rules. The v3 freeze and
its scoring history are in the
[holdout v3 record](reproducibility/fresh-holdout-v3-freeze.md).

## Authorized fresh holdout v3 result (2026-09-27)

The canonical run compared this candidate with installed main on the pinned
142-record corpus. On v3, Success@1 improved 12/30→18/30 and Success@3
16/30→22/30; false answers tied at 0/30. The one-sided 95% paired-bootstrap
lower bound on holdout Success@1 gain was 6.7 pp. Across dev plus holdout,
Success@1 was 30/60→46/60 and Success@3 39/60→52/60. The combined bootstrap
lower bound was 16.7 pp. Treat the development figures as development evidence;
only v3 is independent evidence.

The gate is **inconclusive**, not a release pass: common-platform holdout
Success@3 fell 5/8→4/8, incorrect answered tasks rose 1/6→1/5, and the
`fresh-v3-clean-common-find-ext-markdown-notes` family fell 1/1→0/1 at
Success@1. False answers, offline operation, latency, and memory passed; both
CLI runs completed. The readiness validator rejected the report on the
common-platform Success@3 regression. Keep installed main shipped.

Holdout v3 is consumed. Its frozen prompt pool, dataset, and manifest remain
unchanged; the report is preserved at
[`main-vs-retrieval-v2-focused-query-rules-fresh-holdout-v3.md`](reproducibility/artifacts/main-vs-retrieval-v2-focused-query-rules-fresh-holdout-v3.md).
Do not tune from v3 or score it again. Further development must use development
evidence without using v3 outcomes; independent evaluation of any later
candidate requires a new unseen holdout and explicit authorization.

## Description-only embedding A/B — development rejection (2026-09-27)

The next one-factor experiment compared main-compatible example text with
example-description-only vectors. Both arms used the same frozen 60-task
development cohort and identical 142 parser-v4 records. The separate label
audit checked 24 source pages, 142 indexed examples (139 operational rows),
platform eligibility, and exact accepted example IDs before retrieval. The two
earlier freeze attempts are preserved; neither reached query execution. The
final freeze passed dataset, corpus, and label validation.

The installed-main CLI/data snapshot scored 11/30 Success@1, 15/30
Success@3, 26/30 false answers, and 2/17 incorrect answered. The
main-compatible control candidate tied Success@1, fell to 14/30 Success@3,
and lowered false answers to 23/30 and incorrect answered to 1/15. The
description-only candidate fell to 9/30 Success@1 and 14/30 Success@3, raised
false answers to 29/30, and raised incorrect answered to 9/23. Against the
control it lost two first results, tied top-three results, added six false
answers, and regressed incorrect answered rate from 1/15 to 9/23. Linux and
macOS Success@3 regressed; Windows gains did not offset safety and platform
losses. Reject description-only without tuning.

Network-denied CLI execution had no failures. Latency and memory stayed within
the 20% limit, although treatment fresh-process peak memory reached
282,755,816 B versus main 238,027,496 B (+18.8%). These runs are development
evidence, not independent validation. No holdout dataset, labels, reports, or
results were accessed; the dev-only gate read benchmark freeze manifest
metadata only. V3's result applies only to the focused query-rule candidate.
Keep shipped main. Any next independent score needs a new unseen holdout and
fresh explicit authorization. Full details: [comparison](reproducibility/artifacts/description-embedding-dev-v3-comparison.md),
[machine-readable report](reproducibility/artifacts/description-embedding-dev-v3-comparison.json),
[protocol](reproducibility/artifacts/description-embedding-dev-v3-protocol.md).

## Source-backed operational-example fit filter — development rejection (2026-09-27)

The next one-factor experiment tested whether explicit query actions and
constraints could be checked against each retrieved example before display.
Control and treatment kept the same parser-v4 records, main-compatible
embedding text, focused-v2 rewrites, candidate budget, platform selection,
0.60 raw-distance cutoff, lexical 0.05 reranking, abstention guards, and
top-three limit. Treatment added only the source-backed example-fit filter.

The blind source audit found 28 supported and 32 unsupported tasks, not the
author draft's planned 30/30. Those independent labels were used. The v1 freeze
stopped during preflight before any CLI query; its raw artifacts remain
preserved. The final v2 freeze corrected the corpus-manifest SHA metadata,
passed source-ID/platform validation, and was scored once by the canonical
development-only gate. No holdout data was accessed.

| Run | Success@1 | Success@3 | Coverage | Incorrect answered | False answers |
| --- | ---: | ---: | ---: | ---: | ---: |
| Main reference | 19/28 | 21/28 | 50/60 | 5/26 | 24/32 |
| Fixed-retrieval control | 23/28 | 25/28 | 49/60 | 1/26 | 23/32 |
| Hard-fit filter | 16/28 | 17/28 | 21/60 | 1/18 | 3/32 |

Treatment lost seven first-result and eight top-three tasks versus control,
while abstaining on 28 additional prompts. Success@1 fell on all four
platforms; Success@3 regressed on common, Linux, and Windows relative to main.
Both runs completed under network denial with zero CLI failures. Latency and
memory stayed inside the 20% limits. Quality rejects the filter despite its
false-answer reduction; keep it off and keep shipped main.

This is development evidence from independently audited labels, not
independent candidate validation. Do not tune the filter on this cohort. A
soft constraint-aware reranker was the next hypothesis at that point; it was
later tested on a fresh cohort and rejected, as recorded below. Any release
claim still requires a new unseen holdout and explicit authorization.

The actual installed v0.3.3 sample remains separate: its larger 30,205-row
database cannot be scored with these 142-example corpus labels. The recorded
installed sample and hash-verified inventory remain the evidence for actual
product behavior. Full new experiment details:
[comparison](reproducibility/artifacts/operational-example-fit-v1-comparison.md),
[control](reproducibility/artifacts/operational-example-fit-v1-control.md),
[treatment](reproducibility/artifacts/operational-example-fit-v1-treatment.md),
[protocol](reproducibility/artifacts/operational-example-fit-v1-protocol.md).

## Bounded soft-fit reranking — development rejection (2026-09-27)

A new 60-prompt cohort was authored and source-audited before either run.
The final labels contain 29 answerable and 31 unsupported tasks, 12 families,
and 15 tasks per platform. An independent source-only review marked one
numeric in-place sort prompt unsupported: the pinned page has separate
numeric-sort and in-place-output examples, but no single example covers both.
Raw prompts, initial labels, audit, and correction are preserved. The frozen
dataset SHA-256 is
`418ac923013146d3b60d920aba50a5d9f69afd3da1c658495c226b648a772daa`.

The one-factor treatment added a 0.05 × unsupported-rule-fraction penalty to
the existing lexical-adjusted distance; all query rewrites, embeddings,
candidate selection, cutoff, abstention, and display behavior stayed fixed.
On the same 142 parser-v4 records, the main reference, control, and treatment
measured:

| Run | Success@1 | Success@3 | Coverage | Incorrect answered | False answers |
| --- | ---: | ---: | ---: | ---: | ---: |
| Main reference | 13/29 | 15/29 | 39/60 | 8/23 | 16/31 |
| Control | 19/29 | 22/29 | 41/60 | 2/24 | 17/31 |
| Soft-fit | 18/29 | 22/29 | 41/60 | 2/24 | 17/31 |

Treatment lost one Success@1 task vs control, tied Success@3, and regressed
Linux Success@1 from 5/7 to 4/7. It changed neither coverage nor false-answer
count. Control’s first-result and top-three gains over main came with one
additional false answer, so this ranking-only adjustment cannot meet the
full guardrails. Reject it. Both canonical dev-only gates completed under
network denial without CLI failures; resources stayed within 20%. Neither run
is independent validation. Holdout data was not accessed.

The actual installed v0.3.3 sample is separate: its database contains 30,205
rows and cannot be scored with these 142-record labels. See the
[installed-product sample](reproducibility/artifacts/installed-v0.3.3-smoke-v1.json).
Full controlled results, run configurations, hashes, and the frozen protocol
are in the [comparison](reproducibility/artifacts/operational-soft-fit-dev-v1-comparison.md),
[control](reproducibility/artifacts/operational-soft-fit-dev-v1-control.md),
[treatment](reproducibility/artifacts/operational-soft-fit-dev-v1-treatment.md),
and [freeze](reproducibility/artifacts/operational-soft-fit-dev-v1-freeze.json).

## Dense candidate-budget test — development rejection (2026-09-27)

A new source-audited cohort compared budgets 8 and 16 with all other retrieval
settings fixed. Budget 16 exactly tied budget 8: both scored 20/26 Success@1,
21/26 Success@3, 44/60 coverage, 22/34 false answers, and 1/22 incorrect
supported answers. Source-built main measured 16/26, 17/26, 46/60, 24/34, and
5/22. The candidate control is a broader focused-v2 working-tree configuration;
its gains over main cannot be attributed to candidate budget. Both candidate
arms also had two fewer covered prompts than main, all on Windows.

Reject budget 16; retain budget 8. Offline and resource checks passed, but the
wider pool added no quality value. Both canonical runs are dev-only and
inconclusive for release. The actual installed product was not scored with
these 142-record labels. No holdout data was accessed. An aggregate-only
GPT-6-Sol review found no further ranking factor justified by recorded
evidence, so stop speculative tuning until a concrete hypothesis and fresh
cohort exist. The dev cohort is fully inspected and closed to tuning. See the
[comparison](reproducibility/artifacts/dense-budget-dev-v1-comparison.md),
[protocol](reproducibility/artifacts/dense-budget-dev-v1-protocol.md),
[freeze](reproducibility/artifacts/dense-budget-dev-v1-freeze.json), and
[freeze correction](reproducibility/artifacts/dense-budget-dev-v1-freeze-correction.md).
