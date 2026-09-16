# Evaluation-v2 expanded release evidence

This is the corrected versioned follow-up to the preliminary `evaluation-v2`
freeze from issue #30. The original evaluation-v1 and evaluation-v2 fixture,
provenance, manifest, and scorer artifacts remain unchanged. It supersedes the
attempted expanded freeze `evaluation-v2-release-benchmark-v2`.

## Frozen inputs

- Freeze: `evaluation-v2-release-benchmark-v3` (`2026-09-16`)
- Previous expanded freeze: `evaluation-v2-release-benchmark-v2`
- Splits: 60 dev / 60 holdout; each split has 30 answerable and 30
  unanswerable tasks, 12 disjoint five-task families, and 15 tasks per
  platform (`common`, `linux`, `osx`, `windows`).
- Corpus: 24 pinned tldr-pages pages, 142 examples.
- Source revision:
  `e1cb966e711d73c42d75e79834be7e4dc17264ef`
- Source digest:
  `651cf2818c3a375cbe5f54b65844f0dff381585c09f6603ec26f901da214f3f9`
- Corpus manifest digest:
  `b68651e210e7c0f85ee8ccc503e2d586d5829425aa1ee03fa94edd3271798ad8`
- Expanded freeze manifest digest:
  `4f258311db08cad15c1473c77ff6d98e2fa3b0044990fcdfcbc8110f96fc46dc`
- Dev dataset digest:
  `216c0e26f24fda7df197011be4f8add33b6852b7907b32966b0c77e0a26c947d`
- Holdout dataset digest:
  `1aa1c0a8ec5c550b8a6699654bb5eb56928bd6845f0b3610bb7a8ee368813418`
- Support catalog digest:
  `62cc22160acbe0daa397327fcf94dc5809d11a3c4c390be693f270d4d584f990`
- Full-corpus catalog digest:
  `124cb74e632c6905933481883da7fb6c3bd4924238153f0db2e321a1fea8c68f`
- Intent provenance digest:
  `6f2b5c7a6b3a555aff538d6d85348d612828ff28b48db44c8a3f7610f40c2bfb`
- Scorer digest:
  `006f934dc6e7cb251776bdb8090a014ae0c749e2b976d306b58623e01613ec90`

Files:

- Freeze: `tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json`
- Corpus: `tests/fixtures/tldr-evaluation-v2/manifest.json`
- Dev: `tests/fixtures/evaluation/frozen-dev-v2-expanded.json`
- Holdout: `tests/fixtures/evaluation/frozen-holdout-v2-expanded.json`
- Authoring provenance: `tests/fixtures/evaluation/task-intents-v2-expanded.json`
- Hand-audited support catalog: `tests/fixtures/evaluation/evaluation-v2-support-catalog-expanded.json`
- Full-corpus catalog: `tests/fixtures/evaluation/evaluation-v2-corpus-catalog-expanded.json`
- Dev results: `docs/reproducibility/artifacts/evaluation-v2-expanded-dev-baseline.json`
- Holdout results: `docs/reproducibility/artifacts/evaluation-v2-expanded-holdout-comparison.json`

The manifest's executable `support_audit` v2 binds each family's exact
behavior, platform, and label, plus task-level acceptable example IDs and
rationales. One hundred twenty evidence-bearing hand-check records cover every
frozen task ID. Each record checks platform, behavior, acceptable support, and
abstention (`not_applicable` for answerable tasks). Answerable behavior/support
checks cite hand-audited catalog entries (source page, exact section/line, and
pinned source digest). Each unanswerable check records a deterministic no-match
scan over all 142 examples in the full-corpus catalog: catalog path/ID/digest,
source manifest/content digests, scanned count, normalized task intent, and
`matching_example_ids=[]`.
Provenance records two independent review passes without fabricating a reviewer
identity. Validation rejects mixed-family intents, unrelated support IDs, stale
freeze identities, mutated/unresolved citations, inconsistent hand-check
evidence, missing task records, false/partial abstention scans, stale catalog
digests, and normalized prompt leakage between splits.

The separately pinned 19-entry support catalog maps each accepted example ID
to its source page, source line/position, exact source section, and
hand-audited canonical behavior. The separately pinned full-corpus catalog
indexes every 142 corpus examples with stable IDs, source commands/sections,
and source-section classifications; it is an exhaustive citation inventory,
not an expanded acceptability-label set. The validator checks deterministic ID
linkage, exact catalog linkage, and behavior labels. For each unanswerable task,
the no-match validator derives matching IDs from the full catalog's explicit
`behavior_classification` mapping and requires the recorded scan to equal that
derived list and be empty. It does not infer semantic equivalence or claim
automatic semantic truth beyond the pinned catalog classifications and the
explicitly hand-audited support catalog. The macOS speech family
accepts the plain phrase, custom voice/rate, and Polish-language `say` examples;
this completeness is an explicit catalog adjudication, not automatic semantic
inference. Absence is established only against this pinned, explicitly
hand-audited support subset and the pinned 142-example catalog; the no-match
scan is not a claim about examples outside that catalog and its source-section
classifications are not semantic equivalence judgments.
The generic common-platform `cat` concatenation family accepts both pinned
forms: `>` writes the combined output and `>>` appends it; support is not
narrowed to only one redirection form.

The matching bundle is MIT-licensed tldr-pages content. Questions were
authored before retrieval inspection. Labels and rationales were then
adjudicated against the pinned bundle. Answerable tasks include multiple
acceptable example IDs where the bundle provides equivalent support.

## Reproduce

```sh
python3 scripts/validate_evaluation_v2.py \
  --manifest tests/fixtures/evaluation/evaluation-v2-manifest-expanded.json

cargo run --locked --offline --features dev --bin tldr_subset -- build \
  --manifest tests/fixtures/tldr-evaluation-v2/manifest.json \
  --snapshot tests/fixtures/tldr-evaluation-v2 \
  --output /tmp/askman-evaluation-v2-expanded.db

python3 scripts/evaluate_retrieval.py \
  --artifact /tmp/askman-evaluation-v2-expanded.db \
  --manifest tests/fixtures/tldr-evaluation-v2/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-dev-v2-expanded.json \
  --split dev --retriever keyword

python3 scripts/evaluate_retrieval.py \
  --artifact /tmp/askman-evaluation-v2-expanded.db \
  --manifest tests/fixtures/tldr-evaluation-v2/manifest.json \
  --dataset tests/fixtures/evaluation/frozen-holdout-v2-expanded.json \
  --split holdout --allow-holdout --retriever keyword
```

The authorized runs recorded in the evidence files produced candidate recall
and Success@3 of 1/30 on both splits, coverage 1/60, and zero false answers
on 30 unanswerable tasks. This is a keyword baseline, not a claim that the
retrieval-v2 release is production-quality; dense/hybrid comparison remains
follow-up work.

## ADR-0001 release-gate evidence

The two JSON reports contain exact count/denominator records under
`breakdowns.overall`, `breakdowns.platform`, and `breakdowns.family`. Each
split has 60 tasks: 30 answerable and 30 unanswerable. Overall results:

| split | candidate recall | coverage | Success@1 | Success@3 | incorrect answered | false answers |
| --- | --- | --- | --- | --- | --- | --- |
| dev | 1/30 | 1/60 | 1/30 | 1/30 | 0/1 | 0/30 |
| holdout | 1/30 | 1/60 | 1/30 | 1/30 | 0/1 | 0/30 |

Platform task/answerable/unanswerable counts and metric denominators are:

| split/platform | tasks | answerable | unanswerable | Success@1 | Success@3 | coverage | false answers |
| --- | ---: | ---: | ---: | --- | --- | --- | --- |
| dev/common | 15 | 10 | 5 | 0/10 | 0/10 | 0/15 | 0/5 |
| dev/linux | 15 | 10 | 5 | 0/10 | 0/10 | 0/15 | 0/5 |
| dev/osx | 15 | 5 | 10 | 0/5 | 0/5 | 0/15 | 0/10 |
| dev/windows | 15 | 5 | 10 | 1/5 | 1/5 | 1/15 | 0/10 |
| holdout/common | 15 | 10 | 5 | 1/10 | 1/10 | 1/15 | 0/5 |
| holdout/linux | 15 | 5 | 10 | 0/5 | 0/5 | 0/15 | 0/10 |
| holdout/osx | 15 | 10 | 5 | 0/10 | 0/10 | 0/15 | 0/5 |
| holdout/windows | 15 | 5 | 10 | 0/5 | 0/5 | 0/15 | 0/10 |

The reports include all 12 family rows per split, with exact task counts and
all six metric count/denominator pairs. Concrete Success@3 failures include:

- dev: `dev-v2r1-devcommon-file-content-01` (`show the contents of a file in a shell`), `-02` (`print a file's contents to the terminal`), `-03` (`read a file to standard output`); no candidates were returned.
- holdout: `holdout-v2r1-holdoutcommon-file-content-01` (`concatenate several files into one output file`), `-02` (`join multiple files into a single output`), `-03` (`append the contents of several files into one result file`); no candidates were returned.

This is not a paired `main`-versus-`retrieval-v2` release-gate run. No paired
gain, bootstrap interval, warmed-query latency, or peak-memory comparison was
collected. Recommendation: **inconclusive**. The keyword baseline documents
the pinned fixture protocol only; it cannot establish the ADR promotion
conditions without the paired evidence.

Holdout access is explicit and recorded by the runner. The holdout file is
committed for reproducibility, so this is access-gated evidence, not a secret
holdout.
