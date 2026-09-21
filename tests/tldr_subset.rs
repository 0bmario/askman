#![cfg(feature = "dev")]

use askman::tldr_subset::{
    BuildOptions, InspectOptions, PageKind, QueryOptions, build_artifact,
    build_artifact_with_failure_injection, inspect_page, parse_page, query_artifact,
    query_artifact_for_platform,
};
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use tempfile::tempdir;

const FIXTURE_ROOT: &str = "tests/fixtures/tldr-subset";
const FIXTURE_MANIFEST: &str = "tests/fixtures/tldr-subset/manifest.json";
const REFERENCES_FIXTURE_ROOT: &str = "tests/fixtures/tldr-subset-platform-references";
const REFERENCES_FIXTURE_MANIFEST: &str =
    "tests/fixtures/tldr-subset-platform-references/manifest.json";
const FULL_CORPUS_FIXTURE_ROOT: &str = "tests/fixtures/tldr-full-corpus";
const FULL_CORPUS_FIXTURE_MANIFEST: &str = "tests/fixtures/tldr-full-corpus/manifest.json";

#[test]
fn parses_typed_page_without_losing_order_or_placeholders() {
    let content = fs::read_to_string(format!("{FIXTURE_ROOT}/pages/common/cp.md")).unwrap();
    let page = parse_page(
        "pages/common/cp.md",
        "common",
        "en",
        "fixture-tldr-snapshot-v1",
        &content,
    )
    .unwrap();

    assert_eq!(page.command, "cp");
    assert_eq!(
        page.description,
        "Copy files and directories.\nUse this for local copies.\nMore information: <https://www.gnu.org/software/coreutils/cp>."
    );
    assert_eq!(page.examples.len(), 2);
    assert_eq!(page.examples[0].position, 1);
    assert_eq!(
        page.examples[0].command,
        "cp {{path/to/source}} {{path/to/destination}}"
    );
    assert_eq!(page.examples[1].position, 2);
    assert_eq!(page.original_content, content);
}

#[test]
fn builds_and_queries_a_traceable_source_artifact() {
    let output_dir = tempdir().unwrap();
    let output = output_dir.path().join("subset.db");
    let report = build_artifact(BuildOptions {
        manifest: FIXTURE_MANIFEST.into(),
        snapshot: FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap();

    assert_eq!(report.file_count, 3);
    assert_eq!(report.page_count, 3);
    assert_eq!(report.example_count, 6);
    assert!(output.is_file());

    let results = query_artifact(QueryOptions {
        artifact: output,
        query: "copy another location".to_string(),
        limit: 3,
        platform_explicit: false,
    })
    .unwrap();

    let result = &results[0];
    assert_eq!(result.page_command, "cp");
    assert_eq!(
        result.command,
        "cp {{path/to/source}} {{path/to/destination}}"
    );
    assert!(result.example_id.starts_with("example-"));
    assert!(result.page_id.starts_with("page-"));
    assert_eq!(result.source_path, "pages/common/cp.md");
    assert_eq!(
        result.source_ref,
        "tldr-pages@fixture-tldr-snapshot-v1:pages/common/cp.md"
    );
    assert_eq!(result.platform, "common");
    assert_eq!(result.language, "en");
    assert_eq!(result.example_position, 1);
    assert_eq!(
        result.page_description,
        "Copy files and directories.\nUse this for local copies.\nMore information: <https://www.gnu.org/software/coreutils/cp>."
    );
    assert_eq!(
        result.example_description,
        "Copy a file to another location:"
    );

    let connection = Connection::open(output_dir.path().join("subset.db")).unwrap();
    let original_content: String = connection
        .query_row(
            "SELECT original_content FROM pages WHERE source_path = 'pages/common/cp.md'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(original_content.starts_with("# cp\n"));
    assert!(original_content.contains("`cp {{path/to/source}}"));

    let lexical_text: String = connection
        .query_row(
            "SELECT lexical_text FROM example_lexical WHERE example_id = ?1",
            [&result.example_id],
            |row| row.get(0),
        )
        .unwrap();
    assert!(!lexical_text.contains("# cp"));
    assert!(lexical_text.contains("Copy a file to another location:"));
}

#[test]
fn builds_the_declared_four_platform_corpus_with_explicit_exclusions() {
    let output_dir = tempdir().unwrap();
    let output = output_dir.path().join("full-corpus.db");
    let report = build_artifact(BuildOptions {
        manifest: FULL_CORPUS_FIXTURE_MANIFEST.into(),
        snapshot: FULL_CORPUS_FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap();

    assert_eq!(report.file_count, 7);
    assert_eq!(report.excluded_count, 1);
    assert_eq!(report.page_count, 6);
    assert_eq!(report.example_count, 6);
    assert!(
        report.build_time_ms < 60_000,
        "fixture build unexpectedly exceeded one minute: {} ms",
        report.build_time_ms
    );
    assert!(report.artifact_size_bytes > 0);
    assert!(!report.hardware.is_empty());

    let connection = Connection::open(&output).unwrap();
    let excluded: (String, String) = connection
        .query_row(
            "SELECT status, reason FROM source_files WHERE source_path = 'pages/common/excluded.md'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    assert_eq!(excluded.0, "excluded");
    assert_eq!(
        excluded.1,
        "fixture page documents an explicit parser exclusion"
    );
    let selection: String = connection
        .query_row(
            "SELECT value FROM artifact_metadata WHERE key = 'source_selection'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(selection.contains("pages/osx/pbcopy.md"));
    let recipe: String = connection
        .query_row(
            "SELECT value FROM artifact_metadata WHERE key = 'lexical_query_normalization'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(recipe.contains("AND-join"));

    let linux = query_artifact_for_platform(
        QueryOptions {
            artifact: output.clone(),
            query: "search patterns files".to_string(),
            limit: 10,
            platform_explicit: false,
        },
        "linux",
    )
    .unwrap();
    assert_eq!(linux.len(), 1);
    assert_eq!(linux[0].source_path, "pages/linux/grep.md");

    let osx = query_artifact_for_platform(
        QueryOptions {
            artifact: output.clone(),
            query: "macOS clipboard".to_string(),
            limit: 10,
            platform_explicit: false,
        },
        "osx",
    )
    .unwrap();
    assert_eq!(osx.len(), 1);
    assert_eq!(osx[0].source_path, "pages/osx/pbcopy.md");

    let windows = query_artifact_for_platform(
        QueryOptions {
            artifact: output.clone(),
            query: "formatted Windows".to_string(),
            limit: 10,
            platform_explicit: false,
        },
        "windows",
    )
    .unwrap();
    assert_eq!(windows.len(), 1);
    assert_eq!(windows[0].source_path, "pages/windows/printf.md");

    let page = inspect_page(InspectOptions {
        artifact: output,
        page: "vi".to_string(),
        platform: "common".to_string(),
    })
    .unwrap();
    assert_eq!(page.destinations.len(), 1);
    assert_eq!(page.destinations[0].page_name, "vim");
}

#[test]
fn successful_build_replaces_an_existing_artifact_after_validation() {
    let output_dir = tempdir().unwrap();
    let output = output_dir.path().join("replacement.db");
    build_artifact(BuildOptions {
        manifest: FIXTURE_MANIFEST.into(),
        snapshot: FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap();

    let report = build_artifact(BuildOptions {
        manifest: REFERENCES_FIXTURE_MANIFEST.into(),
        snapshot: REFERENCES_FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap();
    assert_eq!(report.page_count, 10);
    assert_eq!(report.file_count, 10);
    let inspected = inspect_page(InspectOptions {
        artifact: output,
        page: "vi".to_string(),
        platform: "common".to_string(),
    })
    .unwrap();
    assert_eq!(inspected.destinations[0].page_name, "vim");
}

#[test]
fn malformed_rebuild_leaves_previous_artifact_untouched() {
    let output_dir = tempdir().unwrap();
    let output = output_dir.path().join("previous.db");
    build_artifact(BuildOptions {
        manifest: FIXTURE_MANIFEST.into(),
        snapshot: FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap();
    let previous_bytes = fs::read(&output).unwrap();

    let bad_snapshot = tempdir().unwrap();
    write_snapshot_file(
        bad_snapshot.path(),
        "pages/common/bad.md",
        "# bad\n\n- missing command\nnot a command\n",
    );
    let error = build_custom_snapshot(
        bad_snapshot.path(),
        &["pages/common/bad.md"],
        output.clone(),
    )
    .unwrap_err()
    .to_string();

    assert!(error.contains("pages/common/bad.md:4:"), "{error}");
    assert_eq!(fs::read(&output).unwrap(), previous_bytes);
    assert!(!temporary_output_exists(output_dir.path(), "previous.db"));
}

#[test]
fn interrupted_rebuild_leaves_previous_artifact_untouched() {
    let output_dir = tempdir().unwrap();
    let output = output_dir.path().join("previous.db");
    build_artifact(BuildOptions {
        manifest: FIXTURE_MANIFEST.into(),
        snapshot: FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap();
    let previous_bytes = fs::read(&output).unwrap();

    let error = build_artifact_with_failure_injection(
        BuildOptions {
            manifest: FIXTURE_MANIFEST.into(),
            snapshot: FIXTURE_ROOT.into(),
            output: output.clone(),
        },
        Some(1),
    )
    .unwrap_err()
    .to_string();

    assert!(error.contains("failure injection interrupted construction"));
    assert_eq!(fs::read(&output).unwrap(), previous_bytes);
    assert!(!temporary_output_exists(output_dir.path(), "previous.db"));
}

#[test]
fn repeated_builds_have_equivalent_logical_records() {
    let output_dir = tempdir().unwrap();
    let first = output_dir.path().join("first.db");
    let second = output_dir.path().join("second.db");
    for output in [&first, &second] {
        build_artifact(BuildOptions {
            manifest: FULL_CORPUS_FIXTURE_MANIFEST.into(),
            snapshot: FULL_CORPUS_FIXTURE_ROOT.into(),
            output: output.to_path_buf(),
        })
        .unwrap();
    }

    assert_eq!(logical_records(&first), logical_records(&second));
}

#[test]
fn selects_target_platform_before_retrieval() {
    let output_dir = tempdir().unwrap();
    let output = output_dir.path().join("subset.db");
    let report = build_artifact(BuildOptions {
        manifest: REFERENCES_FIXTURE_MANIFEST.into(),
        snapshot: REFERENCES_FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap();

    assert_eq!(report.file_count, 10);
    assert_eq!(report.page_count, 10);
    assert_eq!(report.example_count, 11);

    let linux_results = query_artifact_for_platform(
        QueryOptions {
            artifact: output.clone(),
            query: "formatted Linux syntax".to_string(),
            limit: 10,
            platform_explicit: false,
        },
        "linux",
    )
    .unwrap();
    assert_eq!(linux_results.len(), 1);
    assert_eq!(linux_results[0].source_path, "pages/linux/printf.md");
    assert_eq!(linux_results[0].command, "printf -- \"{{text}}\"");

    let common_results = query_artifact_for_platform(
        QueryOptions {
            artifact: output.clone(),
            query: "formatted common syntax".to_string(),
            limit: 10,
            platform_explicit: false,
        },
        "osx",
    )
    .unwrap();
    assert_eq!(common_results.len(), 1);
    assert_eq!(common_results[0].source_path, "pages/common/printf.md");

    let excluded_windows_results = query_artifact_for_platform(
        QueryOptions {
            artifact: output,
            query: "formatted Windows syntax".to_string(),
            limit: 10,
            platform_explicit: false,
        },
        "linux",
    )
    .unwrap();
    assert!(excluded_windows_results.is_empty());
}

#[test]
fn follows_aliases_and_moved_pages_without_rewriting_destination_commands() {
    let output_dir = tempdir().unwrap();
    let output = output_dir.path().join("subset.db");
    build_artifact(BuildOptions {
        manifest: REFERENCES_FIXTURE_MANIFEST.into(),
        snapshot: REFERENCES_FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap();

    let alias = inspect_page(InspectOptions {
        artifact: output.clone(),
        page: "vi".to_string(),
        platform: "common".to_string(),
    })
    .unwrap();
    assert_eq!(alias.requested_name, "vi");
    assert_eq!(alias.destinations.len(), 1);
    assert_eq!(alias.destinations[0].page_name, "vim");
    assert_eq!(alias.destinations[0].command, "vim");
    assert_eq!(
        alias.destinations[0].examples[0].command,
        "vim {{path/to/file}}"
    );

    let moved = inspect_page(InspectOptions {
        artifact: output.clone(),
        page: "old-printf".to_string(),
        platform: "common".to_string(),
    })
    .unwrap();
    assert_eq!(moved.destinations.len(), 1);
    assert_eq!(moved.destinations[0].page_name, "printf");
    assert_eq!(
        moved.destinations[0].examples[0].command,
        "printf \"{{text}}\""
    );

    let navigation_results = query_artifact(QueryOptions {
        artifact: output,
        query: "documentation original command".to_string(),
        limit: 10,
        platform_explicit: false,
    })
    .unwrap();
    assert!(navigation_results.is_empty());
}

#[test]
fn ordinary_tldr_token_is_searchable_and_not_a_reference() {
    let output_dir = tempdir().unwrap();
    let output = output_dir.path().join("subset.db");
    build_artifact(BuildOptions {
        manifest: REFERENCES_FIXTURE_MANIFEST.into(),
        snapshot: REFERENCES_FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap();

    let results = query_artifact(QueryOptions {
        artifact: output,
        query: "literal tldr token".to_string(),
        limit: 10,
        platform_explicit: false,
    })
    .unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].source_path, "pages/common/tldr-token.md");
    assert_eq!(results[0].command, "echo tldr");
}

#[test]
fn mixed_pages_do_not_index_navigation_examples() {
    let snapshot = tempdir().unwrap();
    write_snapshot_file(
        snapshot.path(),
        "pages/common/mixed.md",
        "# mixed\n\n> A page with operational and navigation examples.\n\n- Run the operational command:\n\n`echo operational`\n\n- View documentation for the original command:\n\n`tldr vim`\n",
    );
    let output_dir = tempdir().unwrap();
    let output = output_dir.path().join("subset.db");
    build_custom_snapshot(snapshot.path(), &["pages/common/mixed.md"], output.clone()).unwrap();

    let navigation_results = query_artifact(QueryOptions {
        artifact: output.clone(),
        query: "documentation original".to_string(),
        limit: 10,
        platform_explicit: false,
    })
    .unwrap();
    assert!(navigation_results.is_empty());

    let operational_results = query_artifact(QueryOptions {
        artifact: output,
        query: "run operational".to_string(),
        limit: 10,
        platform_explicit: false,
    })
    .unwrap();
    assert_eq!(operational_results.len(), 1);
    assert_eq!(operational_results[0].command, "echo operational");
}

#[test]
fn disambiguation_lists_destinations_and_search_keeps_pages_distinct() {
    let output_dir = tempdir().unwrap();
    let output = output_dir.path().join("subset.db");
    build_artifact(BuildOptions {
        manifest: REFERENCES_FIXTURE_MANIFEST.into(),
        snapshot: REFERENCES_FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap();

    let lookup = inspect_page(InspectOptions {
        artifact: output.clone(),
        page: "just".to_string(),
        platform: "common".to_string(),
    })
    .unwrap();
    let destination_names: Vec<&str> = lookup
        .destinations
        .iter()
        .map(|page| page.page_name.as_str())
        .collect();
    assert_eq!(destination_names, ["just.1", "just.js"]);
    assert_ne!(
        lookup.destinations[0].description,
        lookup.destinations[1].description
    );

    let results = query_artifact_for_platform(
        QueryOptions {
            artifact: output,
            query: "run".to_string(),
            limit: 10,
            platform_explicit: false,
        },
        "common",
    )
    .unwrap();
    assert_eq!(results.len(), 2);
    assert_eq!(results[0].command, "just --list");
    assert_eq!(results[1].command, "just --version");
    assert_ne!(results[0].page_id, results[1].page_id);
    assert_ne!(results[0].page_description, results[1].page_description);
}

#[test]
fn malformed_selected_pages_report_exact_source_diagnostics() {
    let snapshot = tempdir().unwrap();
    write_snapshot_file(
        snapshot.path(),
        "pages/common/bad.md",
        "# bad\n\n- missing command\nnot a command\n",
    );
    let output_dir = tempdir().unwrap();
    let error = build_custom_snapshot(
        snapshot.path(),
        &["pages/common/bad.md"],
        output_dir.path().join("subset.db"),
    )
    .unwrap_err()
    .to_string();
    assert_eq!(
        error,
        "pages/common/bad.md:4: example description is not followed by a command"
    );
}

#[test]
fn broken_references_fail_with_the_originating_source_and_line() {
    let snapshot = tempdir().unwrap();
    write_snapshot_file(
        snapshot.path(),
        "pages/common/alias.md",
        "# alias\n\n> This command is an alias of `missing`.\n\n- View documentation for the original command:\n\n`tldr missing`\n",
    );
    let output_dir = tempdir().unwrap();
    let error = build_custom_snapshot(
        snapshot.path(),
        &["pages/common/alias.md"],
        output_dir.path().join("subset.db"),
    )
    .unwrap_err()
    .to_string();
    assert_eq!(
        error,
        "pages/common/alias.md:7: unresolved page reference `missing`"
    );
}

#[test]
fn cyclic_references_fail_with_the_source_path_chain() {
    let snapshot = tempdir().unwrap();
    let content = |name: &str| {
        format!(
            "# {name}\n\n> This command points to another page.\n\n- View documentation for the destination:\n\n`tldr {other}`\n",
            other = if name == "a" { "b" } else { "a" }
        )
    };
    write_snapshot_file(snapshot.path(), "pages/common/a.md", &content("a"));
    write_snapshot_file(snapshot.path(), "pages/common/b.md", &content("b"));
    let output_dir = tempdir().unwrap();
    let error = build_custom_snapshot(
        snapshot.path(),
        &["pages/common/a.md", "pages/common/b.md"],
        output_dir.path().join("subset.db"),
    )
    .unwrap_err()
    .to_string();
    assert!(
        error.contains(
            "pages/common/b.md:7: cyclic page reference: pages/common/a.md -> pages/common/b.md -> pages/common/a.md"
        ),
        "{error}"
    );
}

#[test]
fn parses_reference_kind_without_indexing_navigation_examples() {
    let alias = parse_page(
        "pages/common/vi.md",
        "common",
        "en",
        "fixture-tldr-platform-references-v1",
        &fs::read_to_string(format!("{REFERENCES_FIXTURE_ROOT}/pages/common/vi.md")).unwrap(),
    )
    .unwrap();
    assert_eq!(alias.kind, PageKind::Reference);
    assert_eq!(alias.references[0].destination_name, "vim");
}

fn write_snapshot_file(root: &Path, relative_path: &str, content: &str) {
    let path = root.join(relative_path);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, content).unwrap();
}

fn build_custom_snapshot(
    root: &Path,
    files: &[&str],
    output: PathBuf,
) -> anyhow::Result<askman::tldr_subset::BuildReport> {
    let digest = snapshot_digest_for_files(root, files);
    let file_list = files
        .iter()
        .map(|file| format!("\"{file}\""))
        .collect::<Vec<_>>()
        .join(",");
    let manifest = format!(
        r#"{{
  "schema_version": 3,
  "parser_version": "tldr-subset-v3",
  "source": {{
    "name": "tldr-pages",
    "revision": "fixture-invalid-v1",
    "digest_algorithm": "sha256",
    "digest": "{digest}",
    "url": "https://github.com/tldr-pages/tldr",
    "attribution": "Content from the tldr-pages project.",
    "license": {{"name": "MIT", "url": "https://github.com/tldr-pages/tldr/blob/main/LICENSE.md"}}
  }},
  "language": "en",
  "pages_root": "pages",
  "files": [{file_list}],
  "lexical_index": {{
    "tokenizer": "unicode61",
    "fields": ["page.command", "page.description", "example.description", "example.command"],
    "query_normalization": "split non-alphanumeric except underscore; lowercase ASCII; quote and AND-join unique sorted tokens"
  }}
}}"#
    );
    let manifest_path = root.join("manifest.json");
    fs::write(&manifest_path, manifest).unwrap();
    Ok(build_artifact(BuildOptions {
        manifest: manifest_path,
        snapshot: root.to_path_buf(),
        output,
    })?)
}

fn temporary_output_exists(parent: &Path, file_name: &str) -> bool {
    parent
        .join(format!(".{file_name}.{}.part", std::process::id()))
        .exists()
}

fn logical_records(path: &Path) -> Vec<String> {
    let connection = Connection::open(path).unwrap();
    let mut records = Vec::new();
    records.push(format!(
        "metadata:{:?}",
        connection
            .prepare("SELECT key, value FROM artifact_metadata ORDER BY key")
            .unwrap()
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap()
    ));
    records.push(format!(
        "source:{:?}",
        connection
            .prepare(
                "SELECT source_path, sha256, byte_len, status, reason
                 FROM source_files ORDER BY source_path",
            )
            .unwrap()
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                ))
            })
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap()
    ));
    records.push(format!(
        "pages:{:?}",
        connection
            .prepare(
                "SELECT page_id, page_name, command, description, source_path,
                        source_revision, source_ref, platform, language, page_position,
                        original_content, page_kind
                 FROM pages ORDER BY page_position",
            )
            .unwrap()
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, String>(7)?,
                    row.get::<_, String>(8)?,
                    row.get::<_, i64>(9)?,
                    row.get::<_, String>(10)?,
                    row.get::<_, String>(11)?,
                ))
            })
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap()
    ));
    records.push(format!(
        "examples:{:?}",
        connection
            .prepare(
                "SELECT example_id, page_id, position, description, command, source_line
                 FROM examples ORDER BY page_id, position",
            )
            .unwrap()
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, i64>(5)?,
                ))
            })
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap()
    ));
    records.push(format!(
        "references:{:?}",
        connection
            .prepare(
                "SELECT page_id, position, destination_name, source_line
                 FROM page_references ORDER BY page_id, position",
            )
            .unwrap()
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, i64>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, i64>(3)?,
                ))
            })
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap()
    ));
    records.push(format!(
        "lexical:{:?}",
        connection
            .prepare("SELECT example_id, lexical_text FROM example_lexical ORDER BY example_id")
            .unwrap()
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap()
    ));
    records
}

fn snapshot_digest_for_files(root: &Path, files: &[&str]) -> String {
    let mut entries = files
        .iter()
        .map(|file| (*file, fs::read(root.join(file)).unwrap()))
        .collect::<Vec<_>>();
    entries.sort_by(|left, right| left.0.cmp(right.0));

    let mut hasher = Sha256::new();
    hasher.update(b"askman-tldr-subset-snapshot-v1\n");
    for (path, bytes) in entries {
        hasher.update(path.as_bytes());
        hasher.update([0]);
        hasher.update(bytes.len().to_string().as_bytes());
        hasher.update([0]);
        hasher.update(bytes);
        hasher.update([0]);
    }
    format!("{:x}", hasher.finalize())
}

#[test]
fn rejects_an_unsupported_selected_file_before_publishing() {
    let source_dir = tempdir().unwrap();
    let manifest = source_dir.path().join("manifest.json");
    let original = fs::read_to_string(FIXTURE_MANIFEST).unwrap();
    let invalid = original.replace("pages/common/cp.md", "pages/common/cp.txt");
    fs::write(&manifest, invalid).unwrap();

    let output = source_dir.path().join("subset.db");
    let error = build_artifact(BuildOptions {
        manifest,
        snapshot: FIXTURE_ROOT.into(),
        output: output.clone(),
    })
    .unwrap_err()
    .to_string();

    assert!(error.contains("unsupported selected input"), "{error}");
    assert!(!output.exists());
}

#[test]
fn malformed_pages_fail_explicitly() {
    let error = parse_page(
        "pages/common/bad.md",
        "common",
        "en",
        "fixture-tldr-snapshot-v1",
        "# bad\n\n- missing command\n",
    )
    .unwrap_err()
    .to_string();

    assert!(
        error.contains("example description is not followed by a command"),
        "{error}"
    );
}

#[test]
fn unsupported_page_syntax_fails_explicitly() {
    let error = parse_page(
        "pages/common/unsupported.md",
        "common",
        "en",
        "fixture-tldr-snapshot-v1",
        "# unsupported\n\nThis syntax is not part of the selected subset.\n",
    )
    .unwrap_err()
    .to_string();

    assert!(error.contains("unsupported selected input"), "{error}");
}

#[test]
fn refuses_to_publish_over_the_installed_askman_database() {
    let error = build_artifact(BuildOptions {
        manifest: FIXTURE_MANIFEST.into(),
        snapshot: FIXTURE_ROOT.into(),
        output: askman::db::get_app_dir_path().join("commands.db"),
    })
    .unwrap_err()
    .to_string();

    assert!(
        error.contains("refusing to replace installed Askman database"),
        "{error}"
    );
}

#[test]
fn refuses_to_publish_over_an_executable_adjacent_database() {
    let executable = std::env::current_exe().unwrap();
    let adjacent_database = executable.parent().unwrap().join("commands.db");

    let error = build_artifact(BuildOptions {
        manifest: FIXTURE_MANIFEST.into(),
        snapshot: FIXTURE_ROOT.into(),
        output: adjacent_database,
    })
    .unwrap_err()
    .to_string();

    assert!(
        error.contains("refusing to replace installed Askman database"),
        "{error}"
    );
}
