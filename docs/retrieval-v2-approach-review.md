# Retrieval-v2 approach review and decision — 2026-09-26

Review starts from working tree `f61e3af`; the final focused candidate is
`3494a11`, against main baseline `8bd9fa2` and installed Askman 0.3.3.
Historical v2 evidence includes two dev-only paired gates and one authorized
canonical run; the broad candidate failed its independent holdout. The smaller
candidate was selected on dev only. It was later scored once against fresh
holdout v1 with explicit authorization; the independent gate was inconclusive
and the candidate is not approved.

## Recommendation

The current dev-selected candidate is main-compatible dense-only retrieval
with five focused intent rules, six source-backed query expansions, raw cosine
ranking, a `<= 0.55` distance guard, and early one-example-per-page selection.
It improves main on
the pinned dev records; this is not independent validation. Hybrid adds no
measured value. The prior broad `IntentRulesV1` candidate failed holdout
Success@1 and Success@3 conditions. Keep shipped Askman as the product baseline
because the focused candidate also failed the split-specific independent gate.
Do not tune from either consumed holdout. Any further release candidate needs
fresh independent evaluation and explicit authorization before scoring.

## Latest focused candidate — dev only

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

## Selected retrieval path

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

## Remaining validation

1. Candidate implementation, dev-only paired reports, controlled ablations,
   installed-product sample, and the authorized fresh-holdout report are
   recorded.
2. Candidate `3494a11` did not pass independent validation. Do not tune from
   either consumed holdout. Any next candidate needs new development evidence,
   a separately frozen unseen holdout, and explicit scoring authorization.
3. The exact paired gate uses the 142-record pinned evaluation corpus. The
   installed 0.3.3 database is a different, larger corpus; its sampled behavior
   and stored-row inventory were reported separately. Full-source parsing
   recall for the installed database remains unmeasured.

The focused candidate meets the paired dev gate, but fails the independent
no-regression and bootstrap conditions; the shipped main remains the product
baseline. A passing development fixture alone does not establish improvement
for the installed product corpus.
