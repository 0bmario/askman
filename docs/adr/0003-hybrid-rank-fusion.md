# Hybrid retrieval uses rank fusion

`retrieval-v2` will ship one hybrid retrieval path that combines lexical and dense rankings with reciprocal-rank fusion. Keyword-only and dense-only paths remain development diagnostics and are not user-selectable. A learned second-stage reranker is out of scope for the initial v2 release; the first product path stays explainable and lightweight.
