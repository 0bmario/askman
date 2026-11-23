# Dense candidate budget v1 — freeze correction

Append-only note; the frozen manifest and both run reports remain unchanged.

The freeze records aggregate candidate source hash
`b95c3482177bbd688741683354cea1d8e8531fee7bbc7904006375b7f8500e28`. Its
hashing step omitted `.cargo/config.toml` (`40c0d5ddbcd899fa7f3bcbf40374ca0ebd1421f044504bfe2bfda76c72bcdb09`). The complete hash
used by the canonical runner is
`fe1e84b11b3ef861f1bafd5306bd863922334709a4d03bd4c4a8dc915e407d8d`.

Both control and treatment reports record that same complete working-tree
hash and candidate binary hash
`affea3983ac89afb79f05d5ef43e456834d470a9b5444f204b53271804b412c4`.
The individually listed source-file hashes in the freeze match the evaluated
tree. This omission is retained as a provenance limitation; it does not change
the within-pair result, but the experiment remains development evidence only.
No holdout data was accessed.

After both runs, an aggregate-inspection command also printed a truncated
sample of per-task development failures. No query, label, threshold, or
configuration changes followed. Treat this development cohort as fully
inspected and do not tune another candidate on it.
