use askman::tldr_subset::{BuildOptions, QueryOptions, build_artifact, parse_page, query_artifact};
use rusqlite::Connection;
use std::fs;
use tempfile::tempdir;

const FIXTURE_ROOT: &str = "tests/fixtures/tldr-subset";
const FIXTURE_MANIFEST: &str = "tests/fixtures/tldr-subset/manifest.json";

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
