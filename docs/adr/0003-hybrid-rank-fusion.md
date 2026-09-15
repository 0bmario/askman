# Hybrid retrieval uses rank fusion

`retrieval-v2` will ship one hybrid retrieval path that combines lexical and dense rankings with reciprocal-rank fusion. Keyword-only and dense-only paths remain development diagnostics, not permanent user-selectable retrieval modes. A learned second-stage reranker is out of scope until evidence shows rank fusion cannot meet the release gate; this keeps the first product path explainable and lightweight.
