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

The database is not part of app releases. It lives under its own release tag
(`db-v1`), and `DB_URL` / `DB_SHA256` in `src/db.rs` pin which one a binary
downloads. To ship new data, upload it to a new `db-vN` release and update both
constants in the same commit.
