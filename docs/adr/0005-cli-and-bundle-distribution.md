# Separate CLI and matching-bundle distribution

Publish the Askman CLI to crates.io and publish each compatible matching bundle as a GitHub Release asset with a manifest. This keeps the crate focused on executable code, avoids embedding mutable retrieval data in the package, and allows the binary and data release to be verified and rolled back independently while remaining version-compatible.
