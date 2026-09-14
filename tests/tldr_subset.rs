#![cfg(feature = "dev")]

use askman::tldr_subset::{
    BuildOptions, InspectOptions, PageKind, QueryOptions, build_artifact, inspect_page, parse_page,
    query_artifact, query_artifact_for_platform,
};
use rusqlite::Connection;
use std::fs;
use std::path::{Path, PathBuf};
use tempfile::tempdir;

const FIXTURE_ROOT: &str = "tests/fixtures/tldr-subset";
const FIXTURE_MANIFEST: &str = "tests/fixtures/tldr-subset/manifest.json";
const REFERENCES_FIXTURE_ROOT: &str = "tests/fixtures/tldr-subset-platform-references";
const REFERENCES_FIXTURE_MANIFEST: &str =
    "tests/fixtures/tldr-subset-platform-references/manifest.json";

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
    })
    .unwrap();

    let result = &results[0];
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
    })
    .unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].source_path, "pages/common/tldr-token.md");
    assert_eq!(results[0].command, "echo tldr");
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
            "pages/common/a.md: cyclic page reference: pages/common/a.md -> pages/common/b.md -> pages/common/a.md"
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
    let file_list = files
        .iter()
        .map(|file| format!("\"{file}\""))
        .collect::<Vec<_>>()
        .join(",");
    let manifest = format!(
        r#"{{
  "schema_version": 2,
  "parser_version": "tldr-subset-v2",
  "source": {{
    "name": "tldr-pages",
    "revision": "fixture-invalid-v1",
    "digest_algorithm": "sha256",
    "digest": "0000000000000000000000000000000000000000000000000000000000000000",
    "url": "https://github.com/tldr-pages/tldr",
    "attribution": "Content from the tldr-pages project.",
    "license": {{"name": "MIT", "url": "https://github.com/tldr-pages/tldr/blob/main/LICENSE.md"}}
  }},
  "language": "en",
  "pages_root": "pages",
  "files": [{file_list}]
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
