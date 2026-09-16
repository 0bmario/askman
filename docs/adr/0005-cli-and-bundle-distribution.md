# Separate CLI and matching-bundle distribution

Generate the Askman CLI and matching-bundle artifacts separately as needed. For
the first Better Askman release, publish the matching bundle and manifest as
GitHub Release assets first; then publish compatible CLI version `0.4.0` to
crates.io. Verify hashes, metadata, bundle ID, and declared CLI compatibility
before publishing the crate. The crate does not embed a mutable production
database or model.

A release is complete only when both artifacts are available and this
publication-time version compatibility is verified. ADR 0004 owns runtime
activation, compatible-pair selection, rollback, and fail-closed behavior. This
keeps publication focused on artifact availability and version compatibility
while keeping the crate focused on executable code.
