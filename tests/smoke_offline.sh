#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname -- "$0")/../scripts/smoke_offline.sh"

test_dir="$(mktemp -d)"
trap 'rm -rf "$test_dir"' EXIT
output="$test_dir/output.txt"

expect_rejected() {
    if assert_smoke_result "$output" ls 'ls -1' 2>/dev/null; then
        printf 'Incorrectly accepted: %s\n' "$1" >&2
        exit 1
    fi
}

printf 'ls\nList files.\n\nExamples:\n  One per line:\n   ls -1\n' > "$output"
assert_smoke_result "$output" ls 'ls -1'

printf 'ls\n' > "$output"
expect_rejected 'bare command'
printf 'mv\nls\nExamples:\n   ls -1\n' > "$output"
expect_rejected 'command appears below first result'
printf 'ls\nExamples:\n   ls -a\n' > "$output"
expect_rejected 'wrong example'
printf 'ls\nExamples:\n   ls -a\ngrep\nExamples:\n   ls -1\n' > "$output"
expect_rejected 'example belongs to another result'

printf '%s' "$MODEL_REVISION" > "$test_dir/ref"
verify_model_ref "$test_dir/ref"
printf '\n' >> "$test_dir/ref"
if verify_model_ref "$test_dir/ref" 2>/dev/null; then
    printf '%s\n' 'Incorrectly accepted newline in model ref' >&2
    exit 1
fi
printf '%s\n' 'Harness validation checks passed.'
