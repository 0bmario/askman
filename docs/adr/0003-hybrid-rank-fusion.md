# Hybrid retrieval uses rank fusion

`retrieval-v2` will ship one hybrid retrieval path that combines lexical and
dense rankings with reciprocal-rank fusion. Keyword-only and dense-only paths
remain development diagnostics and are not user-selectable. The candidate
displays at most three final ranked destination pages, with the best example
per page. Dense candidates pass an explicit semantic-distance guard before
fusion, and the fused result applies an explicit weak-match cutoff. If no
candidate qualifies, it prints `No good matches found.` and exits successfully;
it never converts a low-confidence result into a guessed answer or presents
similarity as a confidence percentage.

A learned second-stage reranker is out of scope for the initial v2 release; the
first product path stays explainable and lightweight. Existing CLI formatting
and command/example semantics remain unchanged except for the agreed hybrid
behavior.
