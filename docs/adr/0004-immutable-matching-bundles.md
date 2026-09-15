# Immutable matching bundles

Each Askman release will identify one complete, hash-verified matching bundle containing its corpus, retrieval indexes, embedding model, manifest, and compatible asset versions. The client uses one active bundle offline and changes it only through an explicit update flow. Activation is atomic: partial, mixed, or invalid bundles are rejected, and any previous valid active bundle remains untouched. If no valid active bundle exists, including when it is absent, Askman exits non-zero with an actionable error.
