#!/usr/bin/env bash
set -Eeuo pipefail

# Reproduce the current CLI against fixed public assets. Provisioning is the
# only networked step after Cargo dependencies have been fetched. `run` builds
# and executes the real binary under an OS-level network deny policy.

readonly SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
readonly DB_URL="https://github.com/0bmario/askman/releases/download/v0.3.3/commands.db"
readonly DB_SHA256="0218c1fd18dc6eb1c6b405356c92e47379286cec68f9fea1a70be896d5f71495"
readonly MODEL_REPO="Qdrant/all-MiniLM-L6-v2-onnx"
readonly MODEL_REVISION="5f1b8cd78bc4fb444dd171e59b18f3a3af89a079"
readonly MODEL_BASE_URL="https://huggingface.co/${MODEL_REPO}/resolve/${MODEL_REVISION}"
readonly MODEL_CACHE_DIRNAME="models--Qdrant--all-MiniLM-L6-v2-onnx"
readonly MODEL_ONNX_SHA256="bbd7b466f6d58e646fdc2bd5fd67b2f5e93c0b687011bd4548c420f7bd46f0c5"
readonly MODEL_CONFIG_SHA256="1b4d8e2a3988377ed8b519a31d8d31025a25f1c5f8606998e8014111438efcd7"
readonly MODEL_SPECIAL_TOKENS_SHA256="5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a"
readonly MODEL_TOKENIZER_CONFIG_SHA256="bd2e06a5b20fd1b13ca988bedc8763d332d242381b4fbc98f8fead4524158f79"
readonly MODEL_TOKENIZER_SHA256="da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0"
readonly ORT_VERSION="1.20.0"
readonly ORT_ARCHIVE_NAME="onnxruntime-osx-arm64-1.20.0.tgz"
readonly ORT_URL="https://github.com/microsoft/onnxruntime/releases/download/v1.20.0/${ORT_ARCHIVE_NAME}"
readonly ORT_ARCHIVE_SHA256="2bcfaafa9ff0a3a94f78e3af2f135ffde5bb2d79b08e83a50dbc450b0d20ddae"
readonly ORT_ROOT_DIRNAME="onnxruntime-osx-arm64-1.20.0"
readonly ORT_DYLIB_SHA256="d8be733cb8dd097cfe2b21e069a7462b5ff561625141d9c4b98d866f15bfb852"

usage() {
    printf '%s\n' \
        "Usage:" \
        "  $0 provision RUN_DIR" \
        "  $0 run RUN_DIR" \
        "  $0 evidence RUN_DIR"
}

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        printf '%s\n' "Neither shasum nor sha256sum is available." >&2
        return 1
    fi
}

download_verified() {
    local url="$1"
    local destination="$2"
    local expected="$3"
    local actual

    mkdir -p "$(dirname -- "$destination")"
    if [[ -f "$destination" ]]; then
        actual="$(sha256_file "$destination")"
        if [[ "$actual" == "$expected" ]]; then
            return 0
        fi
        printf 'Existing asset has wrong SHA256: %s\n' "$destination" >&2
        printf 'expected=%s actual=%s\n' "$expected" "$actual" >&2
        return 1
    fi

    local temporary="${destination}.part"
    curl --fail --location --proto '=https' --tlsv1.2 \
        --silent --show-error --output "$temporary" "$url"
    actual="$(sha256_file "$temporary")"
    if [[ "$actual" != "$expected" ]]; then
        printf 'Downloaded asset has wrong SHA256: %s\n' "$url" >&2
        printf 'expected=%s actual=%s\n' "$expected" "$actual" >&2
        return 1
    fi
    mv "$temporary" "$destination"
}

provision() {
    local run_dir="$1"
    local data_dir="$run_dir/data"
    local model_root="$data_dir/models/$MODEL_CACHE_DIRNAME"
    local snapshot_dir="$model_root/snapshots/$MODEL_REVISION"

    mkdir -p "$data_dir" "$data_dir/models"
    download_verified "$DB_URL" "$data_dir/commands.db" "$DB_SHA256"

    local runtime_dir="$run_dir/onnxruntime"
    local runtime_archive="$run_dir/$ORT_ARCHIVE_NAME"
    mkdir -p "$runtime_dir"
    download_verified "$ORT_URL" "$runtime_archive" "$ORT_ARCHIVE_SHA256"
    if [[ ! -d "$runtime_dir/$ORT_ROOT_DIRNAME" ]]; then
        tar -xzf "$runtime_archive" -C "$runtime_dir"
    fi

    # fastembed 4.8.0 asks hf-hub for `refs/main`. Point that reference at a
    # content-addressed commit while keeping each file byte-verified.
    download_verified "$MODEL_BASE_URL/model.onnx" \
        "$snapshot_dir/model.onnx" \
        "$MODEL_ONNX_SHA256"
    download_verified "$MODEL_BASE_URL/config.json" \
        "$snapshot_dir/config.json" \
        "$MODEL_CONFIG_SHA256"
    download_verified "$MODEL_BASE_URL/special_tokens_map.json" \
        "$snapshot_dir/special_tokens_map.json" \
        "$MODEL_SPECIAL_TOKENS_SHA256"
    download_verified "$MODEL_BASE_URL/tokenizer_config.json" \
        "$snapshot_dir/tokenizer_config.json" \
        "$MODEL_TOKENIZER_CONFIG_SHA256"
    download_verified "$MODEL_BASE_URL/tokenizer.json" \
        "$snapshot_dir/tokenizer.json" \
        "$MODEL_TOKENIZER_SHA256"

    mkdir -p "$model_root/refs"
    local reference_tmp="$model_root/refs/main.part"
    # hf-hub uses refs/main as a literal snapshot directory suffix and does
    # not trim its contents when reading it.
    printf '%s' "$MODEL_REVISION" > "$reference_tmp"
    mv "$reference_tmp" "$model_root/refs/main"

    printf '%s\n' "Provisioned fixed assets in $run_dir"
    printf '%s\n' "Database: $DB_URL"
    printf '%s\n' "Embedding model: $MODEL_REPO@$MODEL_REVISION"
}

os_name() {
    uname -s
}

offline_run() {
    local run_dir="$1"
    shift
    local data_dir="$run_dir/data"
    local pinned_runtime_root
    pinned_runtime_root="$(runtime_root "$run_dir")"
    local env_args=(
        "ASKMAN_DATA_DIR=$data_dir"
        "HF_HOME=$data_dir/models"
    )
    env_args+=(
        "DYLD_LIBRARY_PATH=$pinned_runtime_root/lib"
        "NO_COLOR=1"
        "CLICOLOR_FORCE=0"
    )
    /usr/bin/sandbox-exec \
        -p '(version 1) (allow default) (deny network*)' \
        env "${env_args[@]}" "$@"
}

dependency_version() {
    local package_name="$1"
    awk -v package_name="$package_name" '
        $0 == "name = \"" package_name "\"" { getline; sub(/^version = \"/, ""); sub(/\"$/, ""); print; exit }
    ' "$REPO_ROOT/Cargo.lock"
}

verify_asset() {
    local path="$1"
    local expected="$2"
    local actual

    if [[ ! -s "$path" ]]; then
        printf 'Missing provisioned asset: %s\n' "$path" >&2
        return 1
    fi
    actual="$(sha256_file "$path")"
    if [[ "$actual" != "$expected" ]]; then
        printf 'Provisioned asset has wrong SHA256: %s\n' "$path" >&2
        printf 'expected=%s actual=%s\n' "$expected" "$actual" >&2
        return 1
    fi
}

verify_model_ref() {
    local ref="$1"
    local ref_bytes
    local ref_value

    if [[ ! -f "$ref" ]]; then
        printf 'Missing model cache ref: %s\n' "$ref" >&2
        return 1
    fi
    ref_bytes="$(wc -c < "$ref" | tr -d '[:space:]')"
    ref_value="$(<"$ref")"
    if [[ "$ref_bytes" != "${#MODEL_REVISION}" || "$ref_value" != "$MODEL_REVISION" ]]; then
        printf 'Model cache ref does not pin the expected revision: %s\n' "$ref" >&2
        printf 'expected=%s actual=%s\n' "$MODEL_REVISION" "$ref_value" >&2
        return 1
    fi
}

verify_pinned_assets() {
    local run_dir="$1"
    local data_dir="$run_dir/data"
    local model_root="$data_dir/models/$MODEL_CACHE_DIRNAME"
    local model_dir="$model_root/snapshots/$MODEL_REVISION"
    local pinned_runtime_root
    pinned_runtime_root="$(runtime_root "$run_dir")"

    verify_model_ref "$model_root/refs/main"
    verify_asset "$data_dir/commands.db" "$DB_SHA256"
    verify_asset "$model_dir/model.onnx" "$MODEL_ONNX_SHA256"
    verify_asset "$model_dir/config.json" "$MODEL_CONFIG_SHA256"
    verify_asset "$model_dir/special_tokens_map.json" "$MODEL_SPECIAL_TOKENS_SHA256"
    verify_asset "$model_dir/tokenizer_config.json" "$MODEL_TOKENIZER_CONFIG_SHA256"
    verify_asset "$model_dir/tokenizer.json" "$MODEL_TOKENIZER_SHA256"
    verify_asset "$run_dir/$ORT_ARCHIVE_NAME" "$ORT_ARCHIVE_SHA256"
    verify_asset "$pinned_runtime_root/lib/libonnxruntime.1.20.0.dylib" "$ORT_DYLIB_SHA256"
}

runtime_linkage() {
    otool -L "$1" | awk '/onnxruntime/ {print $1; exit}'
}

runtime_root() {
    printf '%s' "$1/onnxruntime/$ORT_ROOT_DIRNAME"
}

write_manifest() {
    local run_dir="$1"
    local binary="$2"
    local data_dir="$run_dir/data"
    local db_path="$data_dir/commands.db"
    local model_dir="$data_dir/models/$MODEL_CACHE_DIRNAME/snapshots/$MODEL_REVISION"
    local pinned_runtime_root
    pinned_runtime_root="$(runtime_root "$run_dir")"
    local revision
    revision="$(git -C "$REPO_ROOT" rev-parse HEAD)"

    {
        printf '%s\n' "code_revision=$revision"
        printf '%s\n' "binary_source=isolated cargo build"
        printf '%s\n' "working_tree=$(git -C "$REPO_ROOT" status --porcelain=v1 | tr '\n' ';')"
        printf '%s\n' "cargo_lock_sha256=$(sha256_file "$REPO_ROOT/Cargo.lock")"
        printf '%s\n' "binary_sha256=$(sha256_file "$binary")"
        printf '%s\n' "database_url=$DB_URL"
        printf '%s\n' "database_sha256=$(sha256_file "$db_path")"
        printf '%s\n' "database_bytes=$(wc -c < "$db_path" | tr -d '[:space:]')"
        printf '%s\n' "model_repo=$MODEL_REPO"
        printf '%s\n' "model_revision=$MODEL_REVISION"
        printf '%s\n' "model_onnx_sha256=$(sha256_file "$model_dir/model.onnx")"
        printf '%s\n' "model_config_sha256=$(sha256_file "$model_dir/config.json")"
        printf '%s\n' "model_special_tokens_sha256=$(sha256_file "$model_dir/special_tokens_map.json")"
        printf '%s\n' "model_tokenizer_config_sha256=$(sha256_file "$model_dir/tokenizer_config.json")"
        printf '%s\n' "model_tokenizer_sha256=$(sha256_file "$model_dir/tokenizer.json")"
        printf '%s\n' "fastembed=$(dependency_version fastembed)"
        printf '%s\n' "sqlite_vec=$(dependency_version sqlite-vec)"
        printf '%s\n' "rusqlite=$(dependency_version rusqlite)"
        printf '%s\n' "rust=$(rustc --version)"
        printf '%s\n' "cargo=$(cargo --version)"
        printf '%s\n' "ort=$(dependency_version ort)"
        printf '%s\n' "ort_sys=$(dependency_version ort-sys)"
        printf '%s\n' "ort_runtime_linkage=$(runtime_linkage "$binary")"
        printf '%s\n' "ort_runtime_version=$ORT_VERSION"
        printf '%s\n' "ort_runtime_archive_sha256=$(sha256_file "$run_dir/$ORT_ARCHIVE_NAME")"
        printf '%s\n' "ort_runtime_dylib_sha256=$(sha256_file "$pinned_runtime_root/lib/libonnxruntime.1.20.0.dylib")"
        printf '%s\n' "os=$(uname -a)"
        printf '%s\n' "os_version=$(sw_vers -productVersion)"
        printf '%s\n' "cpu=$(sysctl -n machdep.cpu.brand_string)"
        printf '%s\n' "cpu_count=$(sysctl -n hw.ncpu)"
        printf '%s\n' "ram_bytes=$(sysctl -n hw.memsize)"
        printf '%s\n' "execution_provider=fastembed default CPU provider"
        printf '%s\n' "embedding_model=AllMiniLML6V2"
        printf '%s\n' "embedding_dimension=384"
        printf '%s\n' "embedding_max_length=512 (fastembed 4.8.0 default)"
        printf '%s\n' "embedding_output=fastembed normalized vectors"
        printf '%s\n' "sqlite_vec_distance=L2 (vec0 default; schema does not declare another metric)"
        printf '%s\n' "ort_intra_threads_policy=Rust available_parallelism at process start (fastembed 4.8.0); effective count not instrumented"
        printf '%s\n' "query_fixture=$run_dir/offline-smoke.tsv"
        printf '%s\n' "query_fixture_sha256=$(sha256_file "$run_dir/offline-smoke.tsv")"
        printf '%s\n' "committed_fixture_sha256=$(git -C "$REPO_ROOT" show HEAD:tests/fixtures/offline-smoke.tsv | shasum -a 256 | awk '{print $1}')"
        printf '%s\n' "network_policy=macOS sandbox-exec deny network*"
        printf '%s\n' "setup_networked=true; query_networked=false"
    } > "$run_dir/run-manifest.txt"
}

assert_smoke_result() {
    local output="$1"
    local expected="$2"
    local expected_example="$3"
    if [[ "$(head -n 1 "$output")" != "$expected" ]]; then
        printf 'Smoke query did not rank the expected command first: %s\n' "$expected" >&2
        return 1
    fi
    if [[ -z "$expected_example" ]] || ! awk -v example="   $expected_example" '
        $0 == "Examples:" { in_examples = 1; next }
        in_examples && $0 ~ /^[^[:space:]]/ { exit }
        in_examples && $0 == example { found = 1 }
        END { exit !found }
    ' "$output"; then
        printf 'Smoke query did not retrieve the expected example: %s\n' "$expected" >&2
        return 1
    fi
}

run_smoke() {
    local run_dir="$1"
    local binary="$run_dir/target/release/askman"
    local pinned_runtime_root
    pinned_runtime_root="$(runtime_root "$run_dir")"

    verify_pinned_assets "$run_dir"
    printf '%s\n' "Building release binary with networking denied..."
    offline_run "$run_dir" env \
        LIBONNXRUNTIME_NO_PKG_CONFIG=1 \
        ORT_LIB_LOCATION="$pinned_runtime_root" \
        ORT_PREFER_DYNAMIC_LINK=1 \
        CARGO_TARGET_DIR="$run_dir/target" \
        cargo build --locked --offline --release --manifest-path "$REPO_ROOT/Cargo.toml"
    if [[ ! -x "$binary" ]]; then
        printf 'Binary is not executable: %s\n' "$binary" >&2
        return 1
    fi

    mkdir -p "$run_dir/results"
    cp "$REPO_ROOT/tests/fixtures/offline-smoke.tsv" "$run_dir/offline-smoke.tsv"
    write_manifest "$run_dir" "$binary"

    printf '%s\n' "Checking OS-level network denial..."
    offline_run "$run_dir" python3 "$SCRIPT_DIR/assert_network_blocked.py" \
        > "$run_dir/network-probe.txt" 2>&1

    : > "$run_dir/smoke-output.txt"
    local number=0
    local query
    local expected
    local expected_example
    local output
    local status
    while IFS=$'\t' read -r query expected expected_example; do
        [[ -z "$query" || "$query" == \#* ]] && continue
        number=$((number + 1))
        output="$run_dir/results/query-${number}.txt"
        if offline_run "$run_dir" "$binary" --linux "$query" > "$output" 2>&1; then
            status=0
        else
            status=$?
        fi
        {
            printf 'query[%d]=%s\n' "$number" "$query"
            printf 'expected_top_command[%d]=%s\n' "$number" "$expected"
            printf 'expected_example[%d]=%s\n' "$number" "$expected_example"
            printf 'exit_status[%d]=%s\n' "$number" "$status"
            sed 's/^/  /' "$output"
            printf '\n'
        } >> "$run_dir/smoke-output.txt"
        if [[ "$status" -ne 0 ]]; then
            printf 'Smoke query failed (exit %s): %s\n' "$status" "$query" >&2
            return "$status"
        fi
        assert_smoke_result "$output" "$expected" "$expected_example"
    done < "$run_dir/offline-smoke.tsv"
    if [[ "$number" -eq 0 ]]; then
        printf '%s\n' "Smoke fixture contains no queries." >&2
        return 1
    fi

    printf '%s\n' "smoke_queries=$number" >> "$run_dir/run-manifest.txt"
    printf '%s\n' "network_probe=passed" >> "$run_dir/run-manifest.txt"
    printf '%s\n' "All $number offline smoke queries exited successfully."
    printf '%s\n' "Manifest: $run_dir/run-manifest.txt"
    printf '%s\n' "Output: $run_dir/smoke-output.txt"
}

run_evidence() {
    local run_dir="$1"
    local data_dir="$run_dir/data"
    local pinned_runtime_root
    pinned_runtime_root="$(runtime_root "$run_dir")"

    verify_pinned_assets "$run_dir"

    local artifact="$run_dir/heldout-lexical.db"
    local dense_artifact="$run_dir/heldout-dense.db"
    local cargo_env=(
        LIBONNXRUNTIME_NO_PKG_CONFIG=1
        ORT_LIB_LOCATION="$pinned_runtime_root"
        ORT_PREFER_DYNAMIC_LINK=1
        CARGO_TARGET_DIR="$run_dir/target"
    )

    # Asset setup/provisioning is complete before this function. Every build,
    # evaluation, and helper process below inherits the network deny policy.
    offline_run "$run_dir" env "${cargo_env[@]}" cargo build --locked --offline \
        --features dev --bin tldr_subset \
        --manifest-path "$REPO_ROOT/Cargo.toml" \
        > "$run_dir/helper-build.txt"
    local helper="$run_dir/target/debug/tldr_subset"
    # macOS sandbox-exec removes DYLD_* variables. Embed the run-directory
    # rpath in this disposable helper so the denied query phase can load the
    # already provisioned runtime without weakening the sandbox.
    if ! otool -l "$helper" | awk -v expected="$pinned_runtime_root/lib" \
        '$1 == "path" && $2 == expected { found = 1 } END { exit !found }'; then
        install_name_tool -add_rpath "$pinned_runtime_root/lib" "$helper"
    fi
    offline_run "$run_dir" "$helper" \
        build \
        --manifest "$REPO_ROOT/tests/fixtures/tldr-full-corpus/manifest.json" \
        --snapshot "$REPO_ROOT/tests/fixtures/tldr-full-corpus" \
        --output "$artifact" \
        > "$run_dir/lexical-build.txt"
    offline_run "$run_dir" "$helper" \
        dense-build \
        --artifact "$artifact" \
        --model-cache "$data_dir/models" \
        --output "$dense_artifact" \
        --recipe description \
        > "$run_dir/dense-build.txt"
    offline_run "$run_dir" python3 "$REPO_ROOT/scripts/assert_network_blocked.py" \
        > "$run_dir/evidence-network-probe.txt" 2>&1
    offline_run "$run_dir" env "${cargo_env[@]}" python3 \
        "$REPO_ROOT/scripts/run_heldout_evidence.py" \
        --artifact "$dense_artifact" \
        --manifest "$REPO_ROOT/tests/fixtures/tldr-full-corpus/manifest.json" \
        --dataset "$REPO_ROOT/tests/fixtures/evaluation/frozen-holdout-v1.json" \
        --hybrid-config "$REPO_ROOT/tests/fixtures/evaluation/hybrid-config-v1.json" \
        --evidence-config "$REPO_ROOT/tests/fixtures/evaluation/heldout-evidence-config-v1.json" \
        --dense-helper "$helper" \
        --model-cache "$data_dir/models" \
        --build-metadata "$run_dir/lexical-build.txt" \
        --dense-build-metadata "$run_dir/dense-build.txt" \
        --network-probe "$run_dir/evidence-network-probe.txt" \
        --output "$run_dir/heldout-evidence.json"

    printf '%s\n' "Evidence: $run_dir/heldout-evidence.json"
}

# Permit the targeted harness checks to call validation functions directly.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0
fi

if [[ $# -ne 2 ]]; then
    usage >&2
    exit 2
fi

if [[ "$(os_name)" != Darwin || "$(uname -m)" != arm64 ]]; then
    printf '%s\n' "This pinned smoke harness currently supports macOS ARM64 only." >&2
    exit 2
fi

case "$1" in
    provision)
        [[ $# -eq 2 ]] || { usage >&2; exit 2; }
        provision "$2"
        ;;
    run)
        run_smoke "$2"
        ;;
    evidence)
        run_evidence "$2"
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
