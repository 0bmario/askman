# Hybrid retrieval uses rank fusion

`retrieval-v2` will ship one hybrid retrieval path that combines lexical and dense rankings with reciprocal-rank fusion, while keeping keyword-only and dense-only paths as diagnostics. A learned second-stage reranker is out of scope until evidence shows rank fusion cannot meet the release gate; this keeps the first product path explainable and lightweight.
