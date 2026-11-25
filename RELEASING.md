# Releasing

1. Update the version in `Cargo.toml` and add the matching `CHANGELOG.md` entry.
2. Run the checks:

   ```bash
   cargo fmt --check
   cargo clippy --all-targets --all-features -- -D warnings
   cargo test
   cargo package
   ```

3. Commit, tag `vX.Y.Z`, and push the commit and tag. The `Release` workflow builds the binaries and creates the GitHub release.
4. Publish to crates.io with `cargo publish`.
5. Check that crates.io shows the new version and that `install.sh` installs it.

## Commands database

The database lives under its own release tag (currently `db-v2`), and `DB_FILE` / `DB_URL` / `DB_SHA256` in `src/db.rs` pin which one a binary
downloads. To ship new data, upload it to a new `db-vN` release and update all three
constants in the same commit. `DB_FILE` must be a new name (for example `commands-v3.db`):
askman downloads a database only when its file is missing, so a new name is what makes
existing installs fetch it. The old file stays in the data directory; mention
`askman --clean` in the CHANGELOG entry.

The Release workflow still copies `db-v1`'s `commands.db` into each app
release, because askman 0.3.3 and older download it from
`releases/latest`. Drop that step once those versions no longer matter.

The Linux binary is built on a pinned `ubuntu-22.04` runner so it loads on
glibc 2.35 and newer; the workflow fails if the binary needs a newer glibc.
