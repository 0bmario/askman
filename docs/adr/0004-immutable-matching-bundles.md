# Immutable matching bundles

Published matching bundle versions are immutable. Every update uses a new bundle ID; an existing bundle ID is never overwritten.

Each Askman release will identify one complete, hash-verified matching bundle containing its corpus, retrieval indexes, embedding model, manifest, and compatible asset versions. The active CLI and matching bundle must always form a compatible pair. The client uses one active bundle offline and changes it only through an explicit update flow. Activation is atomic: partial, mixed, invalid, or incompatible bundles are rejected, and any previous valid active pair remains untouched. Rollback restores a previous valid compatible pair. If no valid active bundle exists, including when it is absent, Askman exits non-zero with an actionable error.
