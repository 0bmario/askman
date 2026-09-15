# Immutable matching bundles

Each Askman release will identify one hash-verified matching bundle containing its corpus, retrieval indexes, and embedding model. The client uses that bundle offline and changes it only through an explicit update flow, preventing silent asset drift and preserving reproducibility.
