use crate::db;
use anyhow::{Context, Result, anyhow, bail};
use rusqlite::{Connection, params, params_from_iter};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Component, Path, PathBuf};

const ARTIFACT_KIND: &str = "askman.tldr-subset";
const SCHEMA_VERSION: u32 = 2;
const PARSER_VERSION: &str = "tldr-subset-v2";
const SUPPORTED_PLATFORMS: [&str; 4] = ["common", "linux", "osx", "windows"];

#[derive(Debug, Clone)]
pub struct BuildOptions {
    pub manifest: PathBuf,
    pub snapshot: PathBuf,
    pub output: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BuildReport {
    pub output: PathBuf,
    pub file_count: usize,
    pub page_count: usize,
    pub example_count: usize,
    pub source_digest: String,
}

#[derive(Debug, Clone)]
pub struct QueryOptions {
    pub artifact: PathBuf,
    pub query: String,
    pub limit: usize,
}

#[derive(Debug, Clone)]
pub struct InspectOptions {
    pub artifact: PathBuf,
    pub page: String,
    pub platform: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SubsetManifest {
    pub schema_version: u32,
    pub parser_version: String,
    pub source: SourceMetadata,
    pub language: String,
    pub pages_root: String,
    pub files: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SourceMetadata {
    pub name: String,
    pub revision: String,
    pub digest_algorithm: String,
    pub digest: String,
    pub url: String,
    pub attribution: String,
    pub license: LicenseMetadata,
}

#[derive(Debug, Clone, Deserialize)]
pub struct LicenseMetadata {
    pub name: String,
    pub url: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PageKind {
    Operational,
    Reference,
    Disambiguation,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PageReference {
    pub destination_name: String,
    pub example_position: usize,
    pub source_line: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Page {
    pub page_id: String,
    pub page_name: String,
    pub command: String,
    pub description: String,
    pub source_path: String,
    pub source_revision: String,
    pub source_ref: String,
    pub platform: String,
    pub language: String,
    pub original_content: String,
    pub examples: Vec<Example>,
    pub kind: PageKind,
    pub references: Vec<PageReference>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Example {
    pub example_id: String,
    pub page_id: String,
    pub position: usize,
    pub description: String,
    pub command: String,
    pub source_line: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct PageLookupResult {
    pub requested_name: String,
    pub platform: String,
    pub destinations: Vec<Page>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct QueryResult {
    pub rank: usize,
    pub example_id: String,
    pub page_id: String,
    pub command: String,
    pub page_description: String,
    pub example_description: String,
    pub source_path: String,
    pub source_ref: String,
    pub source_revision: String,
    pub platform: String,
    pub language: String,
    pub page_position: usize,
    pub example_position: usize,
}

#[derive(Debug)]
struct SourceFile {
    path: String,
    platform: String,
    bytes: Vec<u8>,
    digest: String,
    page: Page,
}

/// Build an isolated SQLite artifact from a manifest and already-provisioned files.
/// No network access or installed Askman database lookup is performed here.
pub fn build_artifact(options: BuildOptions) -> Result<BuildReport> {
    let manifest = read_manifest(&options.manifest)?;
    validate_manifest(&manifest)?;

    let snapshot_root = fs::canonicalize(&options.snapshot).with_context(|| {
        format!(
            "failed to resolve provisioned snapshot root {}",
            options.snapshot.display()
        )
    })?;
    if !snapshot_root.is_dir() {
        bail!(
            "snapshot root is not a directory: {}",
            snapshot_root.display()
        );
    }

    let output = absolute_path(&options.output)?;
    let mut installed_db_paths = vec![absolute_path(&db::get_app_dir_path().join("commands.db"))?];
    if let Ok(executable) = std::env::current_exe()
        && let Some(parent) = executable.parent()
    {
        installed_db_paths.push(absolute_path(&parent.join("commands.db"))?);
    }
    if installed_db_paths.iter().any(|path| path == &output) {
        bail!(
            "refusing to replace installed Askman database: {}",
            options.output.display()
        );
    }
    if output.starts_with(&snapshot_root) {
        bail!(
            "output artifact must be outside the provisioned snapshot: {}",
            options.output.display()
        );
    }

    let source_files = load_source_files(&manifest, &snapshot_root)?;
    validate_source_references(&source_files)?;
    let source_digest = snapshot_digest(&source_files);
    if source_digest != manifest.source.digest.to_ascii_lowercase() {
        bail!(
            "source snapshot digest mismatch: expected {}, got {}",
            manifest.source.digest,
            source_digest
        );
    }

    let output_parent = output
        .parent()
        .ok_or_else(|| anyhow!("output path has no parent: {}", output.display()))?;
    fs::create_dir_all(output_parent).with_context(|| {
        format!(
            "failed to create output directory {}",
            output_parent.display()
        )
    })?;
    let output_name = output
        .file_name()
        .ok_or_else(|| anyhow!("output path has no file name: {}", output.display()))?
        .to_string_lossy();
    let temporary = output_parent.join(format!(".{output_name}.{}.part", std::process::id()));
    if temporary.exists() {
        bail!("temporary output already exists: {}", temporary.display());
    }

    let build_result = write_artifact(
        &temporary,
        &manifest,
        &source_files,
        source_digest.clone(),
        output.clone(),
    );
    match build_result {
        Ok(report) => match fs::rename(&temporary, &output) {
            Ok(()) => Ok(report),
            Err(error) => {
                let _ = fs::remove_file(&temporary);
                Err(error).with_context(|| {
                    format!(
                        "failed to publish replacement artifact {}",
                        output.display()
                    )
                })
            }
        },
        Err(error) => {
            let _ = fs::remove_file(&temporary);
            Err(error)
        }
    }
}

/// Query the lexical index and return source-backed examples with parent identity.
pub fn query_artifact(options: QueryOptions) -> Result<Vec<QueryResult>> {
    query_artifact_for_platform(options, "common")
}

/// Query only the pages selected for one target platform.
pub fn query_artifact_for_platform(
    options: QueryOptions,
    platform: &str,
) -> Result<Vec<QueryResult>> {
    if options.limit == 0 {
        bail!("query limit must be greater than zero");
    }
    validate_platform(platform)?;
    let fts_query = build_fts_query(&options.query)?;
    let conn = Connection::open(&options.artifact)
        .with_context(|| format!("failed to open artifact {}", options.artifact.display()))?;
    validate_artifact(&conn)?;
    let selected_page_ids = selected_page_ids(&conn, platform)?;
    if selected_page_ids.is_empty() {
        return Ok(Vec::new());
    }
    let page_placeholders = std::iter::repeat_n("?", selected_page_ids.len())
        .collect::<Vec<_>>()
        .join(", ");

    let query = format!(
        "SELECT
             e.example_id,
             e.page_id,
             e.command,
             p.description,
             e.description,
             p.source_path,
             p.source_ref,
             p.source_revision,
             p.platform,
             p.language,
             p.page_position,
             e.position
         FROM example_lexical
         JOIN examples AS e ON e.example_id = example_lexical.example_id
         JOIN pages AS p ON p.page_id = e.page_id
         WHERE example_lexical MATCH ?1
           AND p.page_id IN ({page_placeholders})
         ORDER BY bm25(example_lexical), e.example_id",
    );
    let mut statement = conn.prepare(&query)?;
    let query_params = params_from_iter(
        std::iter::once(fts_query.as_str()).chain(selected_page_ids.iter().map(String::as_str)),
    );
    let rows = statement.query_map(query_params, |row| {
        Ok(QueryResult {
            rank: 0,
            example_id: row.get(0)?,
            page_id: row.get(1)?,
            command: row.get(2)?,
            page_description: row.get(3)?,
            example_description: row.get(4)?,
            source_path: row.get(5)?,
            source_ref: row.get(6)?,
            source_revision: row.get(7)?,
            platform: row.get(8)?,
            language: row.get(9)?,
            page_position: row.get::<_, i64>(10)? as usize,
            example_position: row.get::<_, i64>(11)? as usize,
        })
    })?;

    let mut results = Vec::new();
    let mut seen_pages = HashSet::new();
    for row in rows {
        let mut result = row?;
        if !seen_pages.insert(result.page_id.clone()) {
            continue;
        }
        result.rank = results.len() + 1;
        results.push(result);
        if results.len() == options.limit {
            break;
        }
    }
    Ok(results)
}

/// Inspect the full page selected for a name and platform. Reference pages are
/// followed, while disambiguation pages return every distinct destination.
pub fn inspect_page(options: InspectOptions) -> Result<PageLookupResult> {
    validate_platform(&options.platform)?;
    let requested_name = normalize_page_name(&options.page)?;
    let conn = Connection::open(&options.artifact)
        .with_context(|| format!("failed to open artifact {}", options.artifact.display()))?;
    validate_artifact(&conn)?;
    let pages = load_pages(&conn)?;
    let mut stack = Vec::new();
    let destinations = resolve_page_name(&pages, &requested_name, &options.platform, &mut stack)?;

    Ok(PageLookupResult {
        requested_name,
        platform: options.platform,
        destinations,
    })
}

/// Parse one ordinary tldr page while retaining source context and example order.
pub fn parse_page(
    source_path: &str,
    platform: &str,
    language: &str,
    source_revision: &str,
    content: &str,
) -> Result<Page> {
    let mut header_seen = false;
    let mut command = None;
    let mut description_lines = Vec::new();
    let mut examples = Vec::new();
    let mut pending_description: Option<String> = None;

    for (line_number, raw_line) in content.lines().enumerate() {
        let line = raw_line.trim_end_matches('\r');
        let trimmed = line.trim();

        if !header_seen {
            if trimmed.is_empty() {
                continue;
            }
            let Some(header) = trimmed.strip_prefix("# ") else {
                bail!(
                    "{}:{}: expected a tldr page heading",
                    source_path,
                    line_number + 1
                );
            };
            let header = header.trim();
            if header.is_empty() {
                bail!("{}:{}: page heading is empty", source_path, line_number + 1);
            }
            command = Some(header.to_string());
            header_seen = true;
            continue;
        }

        if let Some(rest) = trimmed.strip_prefix('>') {
            if pending_description.is_some() {
                bail!(
                    "{}:{}: example description is not followed by a command",
                    source_path,
                    line_number + 1
                );
            }
            description_lines.push(rest.trim_start().to_string());
            continue;
        }

        if let Some(rest) = trimmed.strip_prefix("- ") {
            if pending_description.is_some() {
                bail!(
                    "{}:{}: example description is not followed by a command",
                    source_path,
                    line_number + 1
                );
            }
            pending_description = Some(rest.trim().to_string());
            continue;
        }

        if let Some(description) = pending_description.take() {
            if trimmed.is_empty() {
                pending_description = Some(description);
                continue;
            }
            let Some(command_text) = trimmed
                .strip_prefix('`')
                .and_then(|value| value.strip_suffix('`'))
            else {
                bail!(
                    "{}:{}: example description is not followed by a command",
                    source_path,
                    line_number + 1
                );
            };
            let position = examples.len() + 1;
            examples.push(Example {
                example_id: String::new(),
                page_id: String::new(),
                position,
                description,
                command: command_text.to_string(),
                source_line: line_number + 1,
            });
            continue;
        }

        if trimmed.starts_with('`') {
            bail!(
                "{}:{}: unsupported selected input: command without an example description",
                source_path,
                line_number + 1
            );
        }

        if !trimmed.is_empty() {
            bail!(
                "{}:{}: unsupported selected input: unrecognized page syntax",
                source_path,
                line_number + 1
            );
        }
    }

    if pending_description.is_some() {
        bail!(
            "{}: example description is not followed by a command",
            source_path
        );
    }
    let command = command.ok_or_else(|| anyhow!("{source_path}: page heading is missing"))?;
    if examples.is_empty() {
        bail!("{source_path}: page contains no supported examples");
    }

    let page_id = deterministic_id("page", &[source_revision, source_path, platform, language]);
    let source_ref = format!("tldr-pages@{source_revision}:{source_path}");
    let page_name = page_name_from_source_path(source_path)?;
    for example in &mut examples {
        example.page_id = page_id.clone();
        example.example_id =
            deterministic_id("example", &[&page_id, &example.position.to_string()]);
    }

    let (kind, references) = classify_page_references(source_path, &examples)?;

    Ok(Page {
        page_id,
        page_name,
        command,
        description: description_lines.join("\n"),
        source_path: source_path.to_string(),
        source_revision: source_revision.to_string(),
        source_ref,
        platform: platform.to_string(),
        language: language.to_string(),
        original_content: content.to_string(),
        examples,
        kind,
        references,
    })
}

fn classify_page_references(
    source_path: &str,
    examples: &[Example],
) -> Result<(PageKind, Vec<PageReference>)> {
    if examples.is_empty()
        || !examples
            .iter()
            .all(|example| is_documentation_navigation(&example.description))
    {
        return Ok((PageKind::Operational, Vec::new()));
    }

    let mut references = Vec::with_capacity(examples.len());
    for example in examples {
        let destination_name = parse_reference_command(&example.command).ok_or_else(|| {
            anyhow!(
                "{}:{}: documentation-navigation example must invoke tldr with a destination",
                source_path,
                example.source_line
            )
        })?;
        references.push(PageReference {
            destination_name,
            example_position: example.position,
            source_line: example.source_line,
        });
    }

    let kind = if references.len() == 1 {
        PageKind::Reference
    } else {
        PageKind::Disambiguation
    };
    Ok((kind, references))
}

fn is_documentation_navigation(description: &str) -> bool {
    let normalized = description.trim().to_ascii_lowercase();
    normalized.starts_with("view documentation") || normalized.starts_with("view the documentation")
}

fn parse_reference_command(command: &str) -> Option<String> {
    let mut tokens = command.split_whitespace();
    if tokens.next()? != "tldr" {
        return None;
    }

    let mut destination_tokens = Vec::new();
    let mut skip_next = false;
    for token in tokens {
        if skip_next {
            skip_next = false;
            continue;
        }
        if token == "-p" || token == "--platform" {
            skip_next = true;
            continue;
        }
        if token.starts_with("--platform=") || token.starts_with("-p=") {
            continue;
        }
        if token.starts_with('-') {
            return None;
        }
        destination_tokens.push(token);
    }
    if skip_next || destination_tokens.is_empty() {
        return None;
    }

    normalize_page_name(&destination_tokens.join("-")).ok()
}

fn page_name_from_source_path(source_path: &str) -> Result<String> {
    let path = Path::new(source_path);
    let name = path
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or_else(|| anyhow!("invalid page source path: {source_path}"))?;
    normalize_page_name(name)
}

fn normalize_page_name(name: &str) -> Result<String> {
    let joined_words = name.split_whitespace().collect::<Vec<_>>().join("-");
    let mut normalized = joined_words.as_str();
    if let Some(without_extension) = normalized.strip_suffix(".md") {
        normalized = without_extension;
    }
    if normalized.is_empty()
        || normalized.contains('/')
        || normalized.contains('\\')
        || normalized.chars().any(char::is_whitespace)
    {
        bail!("invalid page name: {name}");
    }
    Ok(normalized.to_ascii_lowercase())
}

fn validate_platform(platform: &str) -> Result<()> {
    if SUPPORTED_PLATFORMS.contains(&platform) {
        Ok(())
    } else {
        bail!(
            "unsupported target platform `{platform}`; expected one of: {}",
            SUPPORTED_PLATFORMS.join(", ")
        )
    }
}

fn validate_source_references(source_files: &[SourceFile]) -> Result<()> {
    let pages: Vec<Page> = source_files.iter().map(|file| file.page.clone()).collect();
    for platform in SUPPORTED_PLATFORMS {
        let selected: HashSet<String> = pages
            .iter()
            .filter(|page| {
                select_page(&pages, &page.page_name, platform)
                    .is_some_and(|selected| selected.page_id == page.page_id)
            })
            .map(|page| page.page_id.clone())
            .collect();
        for page in &pages {
            if selected.contains(&page.page_id) && page.kind != PageKind::Operational {
                let mut stack = Vec::new();
                resolve_page_name(&pages, &page.page_name, platform, &mut stack)?;
            }
        }
    }
    Ok(())
}

fn select_page<'a>(pages: &'a [Page], page_name: &str, platform: &str) -> Option<&'a Page> {
    let normalized_name = page_name.to_ascii_lowercase();
    pages
        .iter()
        .find(|page| page.page_name == normalized_name && page.platform == platform)
        .or_else(|| {
            pages
                .iter()
                .find(|page| page.page_name == normalized_name && page.platform == "common")
        })
}

fn resolve_page_name(
    pages: &[Page],
    page_name: &str,
    platform: &str,
    stack: &mut Vec<String>,
) -> Result<Vec<Page>> {
    let normalized_name = normalize_page_name(page_name)?;
    let page = select_page(pages, &normalized_name, platform)
        .ok_or_else(|| anyhow!("unresolved page reference `{normalized_name}`"))?;

    if let Some(position) = stack.iter().position(|path| path == &page.source_path) {
        let mut cycle = stack[position..].to_vec();
        cycle.push(page.source_path.clone());
        bail!(
            "{}: cyclic page reference: {}",
            page.source_path,
            cycle.join(" -> ")
        );
    }

    if page.kind == PageKind::Operational {
        return Ok(vec![page.clone()]);
    }

    stack.push(page.source_path.clone());
    let mut destinations = Vec::new();
    for reference in &page.references {
        let destination =
            select_page(pages, &reference.destination_name, platform).ok_or_else(|| {
                anyhow!(
                    "{}:{}: unresolved page reference `{}`",
                    page.source_path,
                    reference.source_line,
                    reference.destination_name
                )
            })?;
        let resolved =
            resolve_page_name(pages, &destination.page_name, platform, stack).map_err(|error| {
                if error.to_string().contains("cyclic page reference") {
                    error
                } else {
                    anyhow!("{}:{}: {}", page.source_path, reference.source_line, error)
                }
            })?;
        for resolved_page in resolved {
            if !destinations
                .iter()
                .any(|existing: &Page| existing.page_id == resolved_page.page_id)
            {
                destinations.push(resolved_page);
            }
        }
    }
    stack.pop();
    Ok(destinations)
}

fn read_manifest(path: &Path) -> Result<SubsetManifest> {
    let bytes =
        fs::read(path).with_context(|| format!("failed to read manifest {}", path.display()))?;
    serde_json::from_slice(&bytes)
        .with_context(|| format!("failed to parse manifest {}", path.display()))
}

fn validate_manifest(manifest: &SubsetManifest) -> Result<()> {
    if manifest.schema_version != SCHEMA_VERSION {
        bail!(
            "unsupported manifest schema version {}, expected {}",
            manifest.schema_version,
            SCHEMA_VERSION
        );
    }
    if manifest.parser_version != PARSER_VERSION {
        bail!(
            "unsupported parser version {}, expected {}",
            manifest.parser_version,
            PARSER_VERSION
        );
    }
    if manifest.language.is_empty() || manifest.pages_root.is_empty() {
        bail!("manifest language and pages_root are required");
    }
    if manifest.source.name != "tldr-pages" {
        bail!("manifest source must be tldr-pages");
    }
    let source_metadata_complete = !manifest.source.revision.is_empty()
        && !manifest.source.url.is_empty()
        && !manifest.source.attribution.is_empty()
        && !manifest.source.license.name.is_empty()
        && !manifest.source.license.url.is_empty();
    if !source_metadata_complete {
        bail!("manifest source revision, URL, attribution, and license metadata are required");
    }
    if manifest.source.digest_algorithm != "sha256"
        || manifest.source.digest.len() != 64
        || !manifest
            .source
            .digest
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        bail!("manifest source digest must be a 64-character SHA256 value");
    }
    if manifest.files.is_empty() {
        bail!("manifest must select at least one file");
    }
    if manifest.pages_root.contains('/') || manifest.pages_root.contains('\\') {
        bail!("manifest pages_root must be one relative directory name");
    }
    Ok(())
}

fn load_source_files(manifest: &SubsetManifest, snapshot_root: &Path) -> Result<Vec<SourceFile>> {
    let mut seen_paths = HashSet::new();
    let mut source_files = Vec::with_capacity(manifest.files.len());

    for path in &manifest.files {
        let platform = validate_selected_path(path, &manifest.pages_root)?;
        if !seen_paths.insert(path) {
            bail!("manifest selects duplicate file: {path}");
        }

        let selected_path = snapshot_root.join(path);
        let canonical_path = fs::canonicalize(&selected_path)
            .with_context(|| format!("selected file is missing: {path}"))?;
        if !canonical_path.starts_with(snapshot_root) {
            bail!("selected file escapes snapshot root: {path}");
        }
        if !canonical_path.is_file() {
            bail!("selected file is not a regular file: {path}");
        }

        let bytes = fs::read(&canonical_path)
            .with_context(|| format!("failed to read selected file: {path}"))?;
        let content = String::from_utf8(bytes.clone())
            .with_context(|| format!("selected file is not UTF-8: {path}"))?;
        let page = parse_page(
            path,
            &platform,
            &manifest.language,
            &manifest.source.revision,
            &content,
        )?;
        source_files.push(SourceFile {
            path: path.clone(),
            platform,
            digest: sha256_hex(&bytes),
            bytes,
            page,
        });
    }

    Ok(source_files)
}

fn validate_selected_path(path: &str, pages_root: &str) -> Result<String> {
    let selected = Path::new(path);
    let has_unsafe_component = selected.components().any(|component| {
        matches!(
            component,
            Component::CurDir | Component::ParentDir | Component::RootDir | Component::Prefix(_)
        )
    });
    let parts: Vec<&str> = path.split('/').collect();
    let extension_is_supported =
        selected.extension().and_then(|value| value.to_str()) == Some("md");
    let valid_shape = parts.len() == 3
        && parts[0] == pages_root
        && matches!(parts[1], "common" | "linux" | "osx" | "windows")
        && !parts[2].is_empty()
        && extension_is_supported;

    if has_unsafe_component || path.contains('\\') || !valid_shape {
        bail!("unsupported selected input: {path}");
    }
    Ok(parts[1].to_string())
}

fn write_artifact(
    temporary: &Path,
    manifest: &SubsetManifest,
    source_files: &[SourceFile],
    source_digest: String,
    output: PathBuf,
) -> Result<BuildReport> {
    let mut conn = Connection::open(temporary)
        .with_context(|| format!("failed to create artifact {}", temporary.display()))?;
    conn.execute_batch(
        "PRAGMA foreign_keys = ON;
         CREATE TABLE artifact_metadata (
             key TEXT PRIMARY KEY NOT NULL,
             value TEXT NOT NULL
         );
         CREATE TABLE source_files (
             source_path TEXT PRIMARY KEY NOT NULL,
             sha256 TEXT NOT NULL,
             byte_len INTEGER NOT NULL,
             status TEXT NOT NULL
         );
         CREATE TABLE pages (
             page_id TEXT PRIMARY KEY NOT NULL,
             page_name TEXT NOT NULL,
             command TEXT NOT NULL,
             description TEXT NOT NULL,
             source_path TEXT UNIQUE NOT NULL,
             source_revision TEXT NOT NULL,
             source_ref TEXT NOT NULL,
             platform TEXT NOT NULL,
             language TEXT NOT NULL,
             page_position INTEGER NOT NULL,
             original_content TEXT NOT NULL,
             page_kind TEXT NOT NULL
         );
         CREATE TABLE examples (
             example_id TEXT PRIMARY KEY NOT NULL,
             page_id TEXT NOT NULL REFERENCES pages(page_id),
             position INTEGER NOT NULL,
             description TEXT NOT NULL,
             command TEXT NOT NULL,
             source_line INTEGER NOT NULL,
             UNIQUE(page_id, position)
         );
         CREATE TABLE page_references (
             page_id TEXT NOT NULL REFERENCES pages(page_id),
             position INTEGER NOT NULL,
             destination_name TEXT NOT NULL,
             source_line INTEGER NOT NULL,
             PRIMARY KEY(page_id, position)
         );
         CREATE VIRTUAL TABLE example_lexical USING fts5(
             example_id UNINDEXED,
             lexical_text
         );
         CREATE INDEX examples_page_id_idx ON examples(page_id);",
    )?;

    let transaction = conn.transaction()?;
    let metadata = [
        ("artifact_kind", ARTIFACT_KIND.to_string()),
        ("schema_version", SCHEMA_VERSION.to_string()),
        ("parser_version", manifest.parser_version.clone()),
        ("source_name", manifest.source.name.clone()),
        ("source_revision", manifest.source.revision.clone()),
        (
            "source_digest_algorithm",
            manifest.source.digest_algorithm.clone(),
        ),
        ("source_digest", source_digest.clone()),
        ("source_url", manifest.source.url.clone()),
        ("source_attribution", manifest.source.attribution.clone()),
        ("content_license_name", manifest.source.license.name.clone()),
        ("content_license_url", manifest.source.license.url.clone()),
        ("language", manifest.language.clone()),
        ("pages_root", manifest.pages_root.clone()),
    ];
    for (key, value) in metadata {
        transaction.execute(
            "INSERT INTO artifact_metadata(key, value) VALUES (?1, ?2)",
            params![key, value],
        )?;
    }

    let mut example_count = 0;
    for (page_index, source_file) in source_files.iter().enumerate() {
        let page_position = page_index + 1;
        transaction.execute(
            "INSERT INTO source_files(source_path, sha256, byte_len, status)
             VALUES (?1, ?2, ?3, 'parsed')",
            params![
                source_file.path,
                source_file.digest,
                source_file.bytes.len() as i64
            ],
        )?;
        transaction.execute(
            "INSERT INTO pages(
                 page_id, page_name, command, description, source_path,
                 source_revision, source_ref, platform, language, page_position,
                 original_content, page_kind
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
            params![
                source_file.page.page_id,
                source_file.page.page_name,
                source_file.page.command,
                source_file.page.description,
                source_file.page.source_path,
                source_file.page.source_revision,
                source_file.page.source_ref,
                source_file.platform,
                source_file.page.language,
                page_position as i64,
                source_file.page.original_content,
                page_kind_name(source_file.page.kind),
            ],
        )?;

        for example in &source_file.page.examples {
            transaction.execute(
                "INSERT INTO examples(example_id, page_id, position, description, command, source_line)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![
                    example.example_id,
                    example.page_id,
                    example.position as i64,
                    example.description,
                    example.command,
                    example.source_line as i64,
                ],
            )?;
            if source_file.page.kind == PageKind::Operational {
                transaction.execute(
                    "INSERT INTO example_lexical(example_id, lexical_text) VALUES (?1, ?2)",
                    params![example.example_id, lexical_text(&source_file.page, example),],
                )?;
            }
            example_count += 1;
        }
        for reference in &source_file.page.references {
            transaction.execute(
                "INSERT INTO page_references(page_id, position, destination_name, source_line)
                 VALUES (?1, ?2, ?3, ?4)",
                params![
                    source_file.page.page_id,
                    reference.example_position as i64,
                    reference.destination_name,
                    reference.source_line as i64,
                ],
            )?;
        }
    }
    transaction.commit()?;

    validate_artifact(&conn)?;
    let accounted_files: i64 =
        conn.query_row("SELECT COUNT(*) FROM source_files", [], |row| row.get(0))?;
    let stored_pages: i64 = conn.query_row("SELECT COUNT(*) FROM pages", [], |row| row.get(0))?;
    let stored_examples: i64 =
        conn.query_row("SELECT COUNT(*) FROM examples", [], |row| row.get(0))?;
    let row_counts_match = accounted_files as usize == source_files.len()
        && stored_pages as usize == source_files.len()
        && stored_examples as usize == example_count;
    if !row_counts_match {
        bail!("artifact row accounting mismatch before publication");
    }

    Ok(BuildReport {
        output,
        file_count: accounted_files as usize,
        page_count: stored_pages as usize,
        example_count: stored_examples as usize,
        source_digest,
    })
}

fn validate_artifact(conn: &Connection) -> Result<()> {
    let integrity: String = conn.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
    if integrity != "ok" {
        bail!("artifact integrity check failed: {integrity}");
    }
    let kind: String = conn.query_row(
        "SELECT value FROM artifact_metadata WHERE key = 'artifact_kind'",
        [],
        |row| row.get(0),
    )?;
    if kind != ARTIFACT_KIND {
        bail!("unsupported artifact kind: {kind}");
    }
    let schema_version: String = conn.query_row(
        "SELECT value FROM artifact_metadata WHERE key = 'schema_version'",
        [],
        |row| row.get(0),
    )?;
    if schema_version != SCHEMA_VERSION.to_string() {
        bail!(
            "unsupported artifact schema version: {}; expected {}",
            schema_version,
            SCHEMA_VERSION
        );
    }
    Ok(())
}

fn page_kind_name(kind: PageKind) -> &'static str {
    match kind {
        PageKind::Operational => "operational",
        PageKind::Reference => "reference",
        PageKind::Disambiguation => "disambiguation",
    }
}

fn page_kind_from_name(name: &str) -> Result<PageKind> {
    match name {
        "operational" => Ok(PageKind::Operational),
        "reference" => Ok(PageKind::Reference),
        "disambiguation" => Ok(PageKind::Disambiguation),
        _ => bail!("unsupported stored page kind: {name}"),
    }
}

fn selected_page_ids(conn: &Connection, platform: &str) -> Result<Vec<String>> {
    let mut statement = conn.prepare("SELECT page_id, page_name, platform FROM pages")?;
    let rows = statement.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
        ))
    })?;
    let mut selected = HashMap::<String, (u8, String)>::new();
    for row in rows {
        let (page_id, page_name, page_platform) = row?;
        let priority = if page_platform == platform {
            2
        } else if page_platform == "common" {
            1
        } else {
            continue;
        };
        let entry = selected.entry(page_name).or_insert((0, String::new()));
        if priority > entry.0 {
            *entry = (priority, page_id);
        }
    }
    let mut page_ids: Vec<String> = selected.into_values().map(|(_, page_id)| page_id).collect();
    page_ids.sort();
    Ok(page_ids)
}

fn load_pages(conn: &Connection) -> Result<Vec<Page>> {
    let mut statement = conn.prepare(
        "SELECT page_id, page_name, command, description, source_path,
                source_revision, source_ref, platform, language, original_content,
                page_kind
         FROM pages
         ORDER BY page_position",
    )?;
    let page_rows = statement.query_map([], |row| {
        let page_id: String = row.get(0)?;
        Ok(Page {
            page_id,
            page_name: row.get(1)?,
            command: row.get(2)?,
            description: row.get(3)?,
            source_path: row.get(4)?,
            source_revision: row.get(5)?,
            source_ref: row.get(6)?,
            platform: row.get(7)?,
            language: row.get(8)?,
            original_content: row.get(9)?,
            examples: Vec::new(),
            kind: page_kind_from_name(&row.get::<_, String>(10)?)
                .map_err(|error| rusqlite::Error::ToSqlConversionFailure(error.into()))?,
            references: Vec::new(),
        })
    })?;
    let mut pages = Vec::new();
    for row in page_rows {
        pages.push(row?);
    }

    let mut examples = conn.prepare(
        "SELECT example_id, page_id, position, description, command, source_line
         FROM examples ORDER BY page_id, position",
    )?;
    let example_rows = examples.query_map([], |row| {
        Ok(Example {
            example_id: row.get(0)?,
            page_id: row.get(1)?,
            position: row.get::<_, i64>(2)? as usize,
            description: row.get(3)?,
            command: row.get(4)?,
            source_line: row.get::<_, i64>(5)? as usize,
        })
    })?;
    let page_indexes: HashMap<String, usize> = pages
        .iter()
        .enumerate()
        .map(|(index, page)| (page.page_id.clone(), index))
        .collect();
    for row in example_rows {
        let example = row?;
        let page_index = page_indexes
            .get(&example.page_id)
            .ok_or_else(|| anyhow!("example references missing page: {}", example.page_id))?;
        pages[*page_index].examples.push(example);
    }

    let mut references = conn.prepare(
        "SELECT page_id, position, destination_name, source_line
         FROM page_references ORDER BY page_id, position",
    )?;
    let reference_rows = references.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            PageReference {
                destination_name: row.get(2)?,
                example_position: row.get::<_, i64>(1)? as usize,
                source_line: row.get::<_, i64>(3)? as usize,
            },
        ))
    })?;
    for row in reference_rows {
        let (page_id, reference) = row?;
        let page_index = page_indexes
            .get(&page_id)
            .ok_or_else(|| anyhow!("reference points to missing page: {page_id}"))?;
        pages[*page_index].references.push(reference);
    }
    Ok(pages)
}

fn lexical_text(page: &Page, example: &Example) -> String {
    [
        page.command.as_str(),
        page.description.as_str(),
        example.description.as_str(),
        example.command.as_str(),
    ]
    .join("\n")
}

fn build_fts_query(query: &str) -> Result<String> {
    let mut tokens = Vec::new();
    let mut current = String::new();
    for character in query.chars() {
        if character.is_alphanumeric() || character == '_' {
            current.push(character.to_ascii_lowercase());
        } else if !current.is_empty() {
            tokens.push(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
        tokens.push(current);
    }
    tokens.sort();
    tokens.dedup();
    if tokens.is_empty() {
        bail!("query contains no searchable keywords");
    }
    Ok(tokens
        .into_iter()
        .map(|token| format!("\"{token}\""))
        .collect::<Vec<_>>()
        .join(" AND "))
}

fn snapshot_digest(source_files: &[SourceFile]) -> String {
    let mut entries: Vec<(&str, &[u8])> = source_files
        .iter()
        .map(|file| (file.path.as_str(), file.bytes.as_slice()))
        .collect();
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

fn deterministic_id(kind: &str, fields: &[&str]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"askman-tldr-subset-id-v1\n");
    hasher.update(kind.as_bytes());
    hasher.update([0]);
    for field in fields {
        hasher.update(field.len().to_string().as_bytes());
        hasher.update([0]);
        hasher.update(field.as_bytes());
        hasher.update([0]);
    }
    format!("{kind}-{:x}", hasher.finalize())
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn absolute_path(path: &Path) -> Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()?.join(path)
    };
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            _ => normalized.push(component.as_os_str()),
        }
    }

    if normalized.exists() {
        return fs::canonicalize(&normalized).or(Ok(normalized));
    }
    if let (Some(parent), Some(file_name)) = (normalized.parent(), normalized.file_name()) {
        if let Ok(canonical_parent) = fs::canonicalize(parent) {
            return Ok(canonical_parent.join(file_name));
        }
    }
    Ok(normalized)
}
