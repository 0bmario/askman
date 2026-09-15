# Separate CLI and matching-bundle distribution

Publish the Askman CLI to crates.io and each compatible matching bundle as a GitHub Release asset with a manifest. Publication may happen independently, but runtime activation and rollback must always select a compatible CLI-plus-bundle pair. Incompatible artifacts are never activated or rolled back independently. This keeps the crate focused on executable code while preserving verified, reproducible asset delivery.
