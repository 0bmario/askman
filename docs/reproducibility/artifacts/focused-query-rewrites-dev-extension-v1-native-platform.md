# Focused query rewrite ablation — dev only

The 60-task `askman-dev-extension-v1` cohort is frozen and uses 142 parser-v4
records. Its extension-search and Windows cross-drive families exposed the
gaps that motivated these rules, so this is exploratory development evidence,
not independent validation. No holdout tasks or results were read.

All variants keep the same main-compatible vectors, top-eight dense budget,
same-page candidates, 0.60 raw-distance cutoff, 0.05 lexical rerank, three
displayed results, and scoped guards. Benchmark `common` tasks use the host's
native platform, matching the product CLI. Full task-level outcomes and hashes
are in
[`focused-query-rewrites-dev-extension-v1-native-platform.json`](focused-query-rewrites-dev-extension-v1-native-platform.json).

| Query mode | Success@1 | Success@3 | Coverage | Incorrect answered | False answers |
| --- | ---: | ---: | ---: | ---: | ---: |
| focused v1 | 15/30 | 22/30 | 24/60 | 2/24 | 0/30 |
| extension rule only | 19/30 | 24/30 | 26/60 | 2/26 | 0/30 |
| cross-drive rule only | 18/30 | 25/30 | 27/60 | 2/27 | 0/30 |
| both rules | 22/30 | 27/30 | 29/60 | 2/29 | 0/30 |

The extension rule raises its family from 0/5 to 4/5 Success@1 and 2/5 to
4/5 Success@3. The Windows cross-drive rule raises its family from 2/5 to 5/5
at both ranks. Together they improve first results without changing false
answers. The exact CLI gate below checks user-visible output mapping and
platform routing.

Reproduce with the pinned parser-v4 artifact and local model cache:

```sh
DYLD_LIBRARY_PATH=/tmp/askman-goal.Fk5Zkh/onnxruntime/onnxruntime-osx-arm64-1.20.0/lib \
ORT_LIB_LOCATION=/tmp/askman-goal.Fk5Zkh/onnxruntime/onnxruntime-osx-arm64-1.20.0 \
ORT_PREFER_DYNAMIC_LINK=1 \
python3 scripts/evaluate_focused_query_rewrites_dev.py \
  --dataset tests/fixtures/evaluation/dev-only-extension-v1.json \
  --manifest tests/fixtures/tldr-evaluation-v2/manifest-v4.json \
  --artifact /tmp/askman-goal.Fk5Zkh/bundle-final-v2/matching.db \
  --dense-helper target/debug/tldr_subset \
  --model-cache /tmp/askman-goal.Fk5Zkh/data/models \
  --output docs/reproducibility/artifacts/focused-query-rewrites-dev-extension-v1-native-platform.json
```

The paired network-denied product gate is
[`main-vs-dev-extension-v1-focused-v2-query-rules-native-platform.md`](main-vs-dev-extension-v1-focused-v2-query-rules-native-platform.md).
