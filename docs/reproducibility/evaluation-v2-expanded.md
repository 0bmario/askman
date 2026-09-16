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
  `49f94adeec52a70e02a9130ba004760492187969dc963e11c2eac2b1c6376a2c`
- Dev dataset digest:
  `216c0e26f24fda7df197011be4f8add33b6852b7907b32966b0c77e0a26c947d`
- Holdout dataset digest:
  `b6cc7ddb34c03e7da460f351bf602a21c95af04a5a352d63da25d857841d5ce7`
- Support catalog digest:
  `71f47833109c5066ca0d54dc67bb69f625cebc88dd60f8dd71a6c2c74555b53c`
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
- Support catalog: `tests/fixtures/evaluation/evaluation-v2-support-catalog-expanded.json`
- Dev results: `docs/reproducibility/artifacts/evaluation-v2-expanded-dev-baseline.json`
- Holdout results: `docs/reproducibility/artifacts/evaluation-v2-expanded-holdout-comparison.json`

The manifest's executable `support_audit` v2 binds each family's exact
behavior, platform, and label, plus task-level acceptable example IDs and
rationales. Twenty-four evidence-bearing hand-check records cover every
family, platform, split, and answerability label; their provenance records the
independent review method without fabricating a reviewer identity. Validation
rejects mixed-family intents, unrelated support IDs, stale freeze identities,
inconsistent hand-check evidence, and normalized prompt leakage between splits.

The separately pinned support catalog maps each accepted example ID to its
source page, source line/position, exact source section, and hand-audited
canonical behavior. Its method is an independent page/section review; the
validator checks deterministic ID linkage, exact catalog linkage, and behavior
labels. It does not infer semantic equivalence or claim automatic semantic
truth beyond the catalog.

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

Holdout access is explicit and recorded by the runner. The holdout file is
committed for reproducibility, so this is access-gated evidence, not a secret
holdout.
