use crate::db;
use anyhow::{Context, Result, anyhow, bail};
use rusqlite::{Connection, params, params_from_iter};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::time::Instant;

const ARTIFACT_KIND: &str = "askman.tldr-subset";
const SCHEMA_VERSION: u32 = 3;
pub const PARSER_VERSION: &str = "tldr-subset-v3";
const SUPPORTED_PLATFORMS: [&str; 4] = ["common", "linux", "osx", "windows"];
const LEXICAL_INDEX_TOKENIZER: &str = "unicode61";
const LEXICAL_QUERY_NORMALIZATION: &str = "split non-alphanumeric except underscore; lowercase ASCII; quote and AND-join unique sorted tokens";
const LEXICAL_INDEX_FIELDS: [&str; 4] = [
    "page.command",
    "page.description",
    "example.description",
    "example.command",
];

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
    pub excluded_count: usize,
    pub build_time_ms: u128,
    pub peak_memory_bytes: Option<u64>,
    pub artifact_size_bytes: u64,
    pub hardware: String,
}

#[derive(Debug, Clone)]
pub struct QueryOptions {
    pub artifact: PathBuf,
    pub query: String,
    pub limit: usize,
    /// Enables target-platform-over-common result ordering; host-default
    /// queries keep pure relevance ordering.
    pub platform_explicit: bool,
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
    #[serde(default)]
    pub exclusions: Vec<SourceExclusion>,
    pub lexical_index: LexicalIndexRecipe,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct SourceExclusion {
    pub path: String,
    pub reason: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct LexicalIndexRecipe {
    pub tokenizer: String,
    pub fields: Vec<String>,
    pub query_normalization: String,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct SourceMetadata {
    pub name: String,
    pub revision: String,
    pub digest_algorithm: String,
    pub digest: String,
    pub url: String,
    pub attribution: String,
    pub license: LicenseMetadata,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
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
    #[serde(skip_serializing)]
    pub page_command: String,
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
    status: SourceFileStatus,
    exclusion_reason: Option<String>,
    page: Option<Page>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SourceFileStatus {
    Parsed,
    Excluded,
}

impl SourceFileStatus {
    fn as_str(self) -> &'static str {
        match self {
            Self::Parsed => "parsed",
            Self::Excluded => "excluded",
        }
    }
}

/// Build an isolated SQLite artifact from a manifest and already-provisioned files.
/// No network access or installed Askman database lookup is performed here.
pub fn build_artifact(options: BuildOptions) -> Result<BuildReport> {
    build_artifact_with_failure_injection(options, None)
}

/// Build an artifact while optionally failing after the requested number of
/// parsed pages have been written. This is a test seam for proving that a
/// failed construction cannot replace an existing artifact.
pub fn build_artifact_with_failure_injection(
    options: BuildOptions,
    fail_after_pages: Option<usize>,
) -> Result<BuildReport> {
    let started_at = Instant::now();
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
        started_at,
        fail_after_pages,
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
    let conn = Connection::open(&options.artifact)
        .with_context(|| format!("failed to open artifact {}", options.artifact.display()))?;
    validate_artifact(&conn)?;
    query_artifact_for_validated_connection(&conn, options, platform)
}

/// Query an artifact through a connection that was validated at its activation
/// boundary. The hybrid path shares its dense connection with lexical search,
/// avoiding a second SQLite open and a second full artifact validation.
pub(crate) fn query_artifact_for_validated_connection(
    conn: &Connection,
    options: QueryOptions,
    platform: &str,
) -> Result<Vec<QueryResult>> {
    if options.limit == 0 {
        bail!("query limit must be greater than zero");
    }
    validate_platform(platform)?;
    let fts_query = build_fts_query(&options.query)?;
    let selected_page_ids = selected_page_ids(conn, platform)?;
    if selected_page_ids.is_empty() {
        return Ok(Vec::new());
    }
    let (order_by, head_params): (String, Vec<&str>) = if options.platform_explicit {
        (
            "CASE WHEN p.platform = ?2 THEN 0 ELSE 1 END, bm25(example_lexical), e.example_id"
                .to_string(),
            vec![fts_query.as_str(), platform],
        )
    } else {
        (
            "bm25(example_lexical), e.example_id".to_string(),
            vec![fts_query.as_str()],
        )
    };
    let placeholder_base = if options.platform_explicit { 3 } else { 2 };
    let page_placeholders = selected_page_ids
        .iter()
        .enumerate()
        .map(|(index, _)| format!("?{}", index + placeholder_base))
        .collect::<Vec<_>>()
        .join(", ");

    let query = format!(
        "SELECT
             e.example_id,
             e.page_id,
             p.command,
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
         ORDER BY {order_by}",
    );
    let mut statement = conn.prepare(&query)?;
    let query_params = params_from_iter(
        head_params
            .into_iter()
            .chain(selected_page_ids.iter().map(String::as_str)),
    );
    let rows = statement.query_map(query_params, |row| {
        Ok(QueryResult {
            rank: 0,
            example_id: row.get(0)?,
            page_id: row.get(1)?,
            page_command: row.get(2)?,
            command: row.get(3)?,
            page_description: row.get(4)?,
            example_description: row.get(5)?,
            source_path: row.get(6)?,
            source_ref: row.get(7)?,
            source_revision: row.get(8)?,
            platform: row.get(9)?,
            language: row.get(10)?,
            page_position: row.get::<_, i64>(11)? as usize,
            example_position: row.get::<_, i64>(12)? as usize,
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
    let destinations =
        resolve_page_name(&pages, &requested_name, &options.platform, &mut stack, None)?;

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
    let pages: Vec<Page> = source_files
        .iter()
        .filter_map(|file| file.page.clone())
        .collect();
    validate_page_references(&pages)
}

fn validate_page_references(pages: &[Page]) -> Result<()> {
    let mut identities = HashSet::new();
    for page in pages {
        if !identities.insert((&page.platform, &page.page_name)) {
            bail!(
                "duplicate page identity: {} on platform {}",
                page.page_name,
                page.platform
            );
        }
    }

    for platform in SUPPORTED_PLATFORMS {
        let selected: HashSet<String> = pages
            .iter()
            .filter(|page| {
                select_page(&pages, &page.page_name, platform)
                    .is_some_and(|selected| selected.page_id == page.page_id)
            })
            .map(|page| page.page_id.clone())
            .collect();
        for page in pages {
            if selected.contains(&page.page_id) && page.kind != PageKind::Operational {
                let mut stack = Vec::new();
                resolve_page_name(&pages, &page.page_name, platform, &mut stack, None)?;
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
    incoming_reference: Option<(&str, usize)>,
) -> Result<Vec<Page>> {
    let normalized_name = normalize_page_name(page_name)?;
    let page = select_page(pages, &normalized_name, platform)
        .ok_or_else(|| anyhow!("unresolved page reference `{normalized_name}`"))?;

    if let Some(position) = stack.iter().position(|path| path == &page.source_path) {
        let mut cycle = stack[position..].to_vec();
        cycle.push(page.source_path.clone());
        let location = incoming_reference
            .map(|(source_path, source_line)| format!("{source_path}:{source_line}"))
            .unwrap_or_else(|| page.source_path.clone());
        bail!("{location}: cyclic page reference: {}", cycle.join(" -> "));
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
        let resolved = resolve_page_name(
            pages,
            &destination.page_name,
            platform,
            stack,
            Some((&page.source_path, reference.source_line)),
        )
        .map_err(|error| {
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

pub(crate) fn validate_manifest(manifest: &SubsetManifest) -> Result<()> {
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
    if manifest.language != "en" || manifest.pages_root.is_empty() {
        bail!("manifest language must be `en` and pages_root is required");
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

    let expected_fields = LEXICAL_INDEX_FIELDS
        .iter()
        .map(|field| (*field).to_string())
        .collect::<Vec<_>>();
    if manifest.lexical_index.tokenizer != LEXICAL_INDEX_TOKENIZER
        || manifest.lexical_index.fields != expected_fields
        || manifest.lexical_index.query_normalization != LEXICAL_QUERY_NORMALIZATION
    {
        bail!("manifest lexical_index recipe does not match the builder");
    }

    let mut selected_paths = HashSet::new();
    for path in &manifest.files {
        validate_selected_path(path, &manifest.pages_root)?;
        if !selected_paths.insert(path) {
            bail!("manifest selects duplicate file: {path}");
        }
    }

    let mut excluded_paths = HashSet::new();
    for exclusion in &manifest.exclusions {
        validate_selected_path(&exclusion.path, &manifest.pages_root)?;
        if exclusion.reason.trim().is_empty() {
            bail!("manifest exclusion reason is empty: {}", exclusion.path);
        }
        if !excluded_paths.insert(&exclusion.path) {
            bail!("manifest excludes duplicate file: {}", exclusion.path);
        }
        if !selected_paths.contains(&exclusion.path) {
            bail!(
                "manifest exclusion is not in files selection: {}",
                exclusion.path
            );
        }
    }
    Ok(())
}

fn load_source_files(manifest: &SubsetManifest, snapshot_root: &Path) -> Result<Vec<SourceFile>> {
    let mut source_files = Vec::with_capacity(manifest.files.len());
    let exclusions: HashMap<&str, &str> = manifest
        .exclusions
        .iter()
        .map(|exclusion| (exclusion.path.as_str(), exclusion.reason.as_str()))
        .collect();
    let mut failures = Vec::new();

    for path in &manifest.files {
        let platform = validate_selected_path(path, &manifest.pages_root)?;

        let selected_path = snapshot_root.join(path);
        let canonical_path = match fs::canonicalize(&selected_path) {
            Ok(path) => path,
            Err(error) => {
                failures.push(format!("{path}: selected file is missing ({error})"));
                continue;
            }
        };
        if !canonical_path.starts_with(snapshot_root) {
            bail!("selected file escapes snapshot root: {path}");
        }
        if !canonical_path.is_file() {
            failures.push(format!("{path}: selected file is not a regular file"));
            continue;
        }

        let bytes = match fs::read(&canonical_path) {
            Ok(bytes) => bytes,
            Err(error) => {
                failures.push(format!("{path}: failed to read selected file ({error})"));
                continue;
            }
        };
        let digest = sha256_hex(&bytes);
        if let Some(reason) = exclusions.get(path.as_str()) {
            source_files.push(SourceFile {
                path: path.clone(),
                platform,
                bytes,
                digest,
                status: SourceFileStatus::Excluded,
                exclusion_reason: Some((*reason).to_string()),
                page: None,
            });
            continue;
        }

        let content = match String::from_utf8(bytes.clone()) {
            Ok(content) => content,
            Err(error) => {
                failures.push(format!("{path}: selected file is not UTF-8 ({error})"));
                continue;
            }
        };
        let page = match parse_page(
            path,
            &platform,
            &manifest.language,
            &manifest.source.revision,
            &content,
        ) {
            Ok(page) => page,
            Err(error) => {
                failures.push(error.to_string());
                continue;
            }
        };
        source_files.push(SourceFile {
            path: path.clone(),
            platform,
            bytes,
            digest,
            status: SourceFileStatus::Parsed,
            exclusion_reason: None,
            page: Some(page),
        });
    }

    if !failures.is_empty() {
        if failures.len() == 1 {
            bail!("{}", failures[0]);
        }
        bail!(
            "artifact promotion blocked by selected page failures:\n{}",
            failures.join("\n")
        );
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
    started_at: Instant,
    fail_after_pages: Option<usize>,
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
             status TEXT NOT NULL CHECK(status IN ('parsed', 'excluded')),
             reason TEXT NOT NULL
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
        (
            "source_selection",
            serde_json::to_string(&manifest.files).expect("source selection is serializable"),
        ),
        (
            "source_exclusions",
            serde_json::to_string(&manifest.exclusions)
                .expect("source exclusions are serializable"),
        ),
        (
            "lexical_index_tokenizer",
            manifest.lexical_index.tokenizer.clone(),
        ),
        (
            "lexical_index_fields",
            serde_json::to_string(&manifest.lexical_index.fields)
                .expect("lexical fields are serializable"),
        ),
        (
            "lexical_query_normalization",
            manifest.lexical_index.query_normalization.clone(),
        ),
    ];
    for (key, value) in metadata {
        transaction.execute(
            "INSERT INTO artifact_metadata(key, value) VALUES (?1, ?2)",
            params![key, value],
        )?;
    }

    let mut example_count = 0;
    let mut page_count = 0;
    for source_file in source_files {
        transaction.execute(
            "INSERT INTO source_files(source_path, sha256, byte_len, status, reason)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                source_file.path,
                source_file.digest,
                source_file.bytes.len() as i64,
                source_file.status.as_str(),
                source_file.exclusion_reason.as_deref().unwrap_or(""),
            ],
        )?;

        let Some(page) = source_file.page.as_ref() else {
            continue;
        };
        page_count += 1;
        let page_position = page_count;
        transaction.execute(
            "INSERT INTO pages(
                 page_id, page_name, command, description, source_path,
                 source_revision, source_ref, platform, language, page_position,
                 original_content, page_kind
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
            params![
                page.page_id,
                page.page_name,
                page.command,
                page.description,
                page.source_path,
                page.source_revision,
                page.source_ref,
                source_file.platform,
                page.language,
                page_position as i64,
                page.original_content,
                page_kind_name(page.kind),
            ],
        )?;

        for example in &page.examples {
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
            if page.kind == PageKind::Operational
                && !is_documentation_navigation(&example.description)
            {
                transaction.execute(
                    "INSERT INTO example_lexical(example_id, lexical_text) VALUES (?1, ?2)",
                    params![example.example_id, lexical_text(page, example),],
                )?;
            }
            example_count += 1;
        }
        for reference in &page.references {
            transaction.execute(
                "INSERT INTO page_references(page_id, position, destination_name, source_line)
                 VALUES (?1, ?2, ?3, ?4)",
                params![
                    page.page_id,
                    reference.example_position as i64,
                    reference.destination_name,
                    reference.source_line as i64,
                ],
            )?;
        }

        if fail_after_pages.is_some_and(|limit| page_count >= limit) {
            bail!("failure injection interrupted construction after {page_count} pages");
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
        && stored_pages as usize == page_count
        && stored_examples as usize == example_count;
    if !row_counts_match {
        bail!("artifact row accounting mismatch before publication");
    }

    let artifact_size_bytes = fs::metadata(temporary)
        .with_context(|| format!("failed to stat artifact {}", temporary.display()))?
        .len();
    let peak_memory_bytes = process_peak_memory_bytes();
    let excluded_count = source_files
        .iter()
        .filter(|source_file| source_file.status == SourceFileStatus::Excluded)
        .count();

    Ok(BuildReport {
        output,
        file_count: accounted_files as usize,
        page_count: stored_pages as usize,
        example_count: stored_examples as usize,
        source_digest,
        excluded_count,
        build_time_ms: started_at.elapsed().as_millis(),
        peak_memory_bytes,
        artifact_size_bytes,
        hardware: hardware_label(),
    })
}

pub(crate) fn validate_artifact(conn: &Connection) -> Result<()> {
    let integrity: String = conn.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
    if integrity != "ok" {
        bail!("artifact integrity check failed: {integrity}");
    }
    let kind = artifact_metadata(conn, "artifact_kind")?;
    if kind != ARTIFACT_KIND {
        bail!("unsupported artifact kind: {kind}");
    }
    let schema_version = artifact_metadata(conn, "schema_version")?;
    if schema_version != SCHEMA_VERSION.to_string() {
        bail!(
            "unsupported artifact schema version: {}; expected {}",
            schema_version,
            SCHEMA_VERSION
        );
    }

    let parser_version = artifact_metadata(conn, "parser_version")?;
    if parser_version != PARSER_VERSION {
        bail!("unsupported artifact parser version: {parser_version}");
    }
    if artifact_metadata(conn, "language")? != "en" {
        bail!("artifact language is not English");
    }
    let artifact_source_revision = artifact_metadata(conn, "source_revision")?;
    if artifact_source_revision.is_empty() {
        bail!("artifact source revision is empty");
    }
    let source_digest = artifact_metadata(conn, "source_digest")?;
    if source_digest.len() != 64 || !source_digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        bail!("artifact source digest is invalid");
    }
    if artifact_metadata(conn, "source_digest_algorithm")? != "sha256" {
        bail!("artifact source digest algorithm is not SHA256");
    }
    if artifact_metadata(conn, "lexical_index_tokenizer")? != LEXICAL_INDEX_TOKENIZER {
        bail!("artifact lexical index tokenizer does not match the builder");
    }
    let stored_fields: Vec<String> =
        serde_json::from_str(&artifact_metadata(conn, "lexical_index_fields")?)
            .context("artifact lexical index fields are invalid JSON")?;
    let expected_fields = LEXICAL_INDEX_FIELDS
        .iter()
        .map(|field| (*field).to_string())
        .collect::<Vec<_>>();
    if stored_fields != expected_fields
        || artifact_metadata(conn, "lexical_query_normalization")? != LEXICAL_QUERY_NORMALIZATION
    {
        bail!("artifact lexical index recipe does not match the builder");
    }

    let selected_paths: Vec<String> =
        serde_json::from_str(&artifact_metadata(conn, "source_selection")?)
            .context("artifact source selection is invalid JSON")?;
    let exclusions: Vec<SourceExclusion> =
        serde_json::from_str(&artifact_metadata(conn, "source_exclusions")?)
            .context("artifact source exclusions are invalid JSON")?;
    let pages_root = artifact_metadata(conn, "pages_root")?;
    if pages_root.is_empty() {
        bail!("artifact pages_root is empty");
    }
    for path in &selected_paths {
        validate_selected_path(path, &pages_root)?;
    }
    for exclusion in &exclusions {
        validate_selected_path(&exclusion.path, &pages_root)?;
        if exclusion.reason.trim().is_empty() {
            bail!("artifact exclusion reason is empty: {}", exclusion.path);
        }
    }
    let exclusion_reasons: HashMap<&str, &str> = exclusions
        .iter()
        .map(|exclusion| (exclusion.path.as_str(), exclusion.reason.as_str()))
        .collect();

    let mut source_entries = Vec::new();
    let mut statement = conn.prepare(
        "SELECT source_path, sha256, byte_len, status, reason
         FROM source_files ORDER BY rowid",
    )?;
    let rows = statement.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, i64>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
        ))
    })?;
    for row in rows {
        let (path, digest, byte_len, status, reason) = row?;
        if digest.len() != 64
            || !digest.bytes().all(|byte| byte.is_ascii_hexdigit())
            || byte_len < 0
        {
            bail!("invalid source identity record: {path}");
        }
        match status.as_str() {
            "parsed" if reason.is_empty() => {}
            "excluded" => {
                let Some(expected_reason) = exclusion_reasons.get(path.as_str()) else {
                    bail!("excluded source has no manifest reason: {path}");
                };
                if reason != *expected_reason {
                    bail!("excluded source reason mismatch: {path}");
                }
            }
            _ => bail!("invalid source file status: {path}: {status}"),
        }
        source_entries.push((path, status));
    }
    let stored_paths: Vec<String> = source_entries
        .iter()
        .map(|(path, _)| path.clone())
        .collect();
    if stored_paths != selected_paths {
        bail!("artifact source selection row accounting mismatch");
    }
    let stored_excluded_paths: HashSet<&str> = source_entries
        .iter()
        .filter(|(_, status)| status == "excluded")
        .map(|(path, _)| path.as_str())
        .collect();
    if stored_excluded_paths.len() != exclusions.len()
        || exclusions
            .iter()
            .any(|exclusion| !stored_excluded_paths.contains(exclusion.path.as_str()))
    {
        bail!("artifact exclusion row accounting mismatch");
    }

    let mut page_paths = HashSet::new();
    let mut page_statement = conn.prepare(
        "SELECT page_id, page_name, source_path, source_revision, source_ref,
                platform, language, page_position
         FROM pages ORDER BY page_position",
    )?;
    let page_rows = page_statement.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, String>(5)?,
            row.get::<_, String>(6)?,
            row.get::<_, i64>(7)?,
        ))
    })?;
    for (index, row) in page_rows.enumerate() {
        let (
            page_id,
            page_name,
            source_path,
            source_revision,
            source_ref,
            platform,
            language,
            page_position,
        ) = row?;
        if page_position != index as i64 + 1 {
            bail!("page row accounting mismatch at {source_path}");
        }
        validate_platform(&platform)?;
        let expected_page_name = page_name_from_source_path(&source_path)?;
        if page_name != expected_page_name {
            bail!("page name identity mismatch: {source_path}");
        }
        let expected_page_id = deterministic_id(
            "page",
            &[&source_revision, &source_path, &platform, &language],
        );
        if page_id != expected_page_id
            || source_revision != artifact_source_revision
            || source_ref != format!("tldr-pages@{source_revision}:{source_path}")
        {
            bail!("page source identity mismatch: {source_path}");
        }
        if !page_paths.insert(source_path.clone()) {
            bail!("duplicate stored page source: {source_path}");
        }
    }
    for (path, status) in &source_entries {
        if status == "parsed" && !page_paths.contains(path) {
            bail!("parsed source has no page row: {path}");
        }
        if status == "excluded" && page_paths.contains(path) {
            bail!("excluded source has a page row: {path}");
        }
    }

    let pages = load_pages(conn)?;
    validate_page_references(&pages)?;
    let mut expected_lexical = HashMap::new();
    let mut expected_examples = 0usize;
    for page in &pages {
        if page.examples.is_empty() {
            bail!("page contains no stored examples: {}", page.source_path);
        }
        for (index, example) in page.examples.iter().enumerate() {
            if example.page_id != page.page_id
                || example.position != index + 1
                || example.example_id
                    != deterministic_id("example", &[&page.page_id, &(index + 1).to_string()])
                || example.source_line == 0
            {
                bail!("example source identity mismatch: {}", page.source_path);
            }
            expected_examples += 1;
            if page.kind == PageKind::Operational
                && !is_documentation_navigation(&example.description)
            {
                expected_lexical.insert(example.example_id.clone(), lexical_text(page, example));
            }
        }
        if page.kind == PageKind::Operational && !page.references.is_empty() {
            bail!("operational page has references: {}", page.source_path);
        }
        for reference in &page.references {
            if !page
                .examples
                .iter()
                .any(|example| example.position == reference.example_position)
            {
                bail!("reference position is missing: {}", page.source_path);
            }
        }
    }

    let stored_lexical: HashMap<String, String> = conn
        .prepare("SELECT example_id, lexical_text FROM example_lexical")?
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?
        .collect::<rusqlite::Result<HashMap<_, _>>>()?;
    if stored_lexical != expected_lexical {
        bail!("lexical index row accounting mismatch");
    }

    let stored_examples: i64 =
        conn.query_row("SELECT COUNT(*) FROM examples", [], |row| row.get(0))?;
    let stored_references: i64 =
        conn.query_row("SELECT COUNT(*) FROM page_references", [], |row| row.get(0))?;
    let expected_references: usize = pages.iter().map(|page| page.references.len()).sum();
    let parsed_count = source_entries
        .iter()
        .filter(|(_, status)| status == "parsed")
        .count();
    if source_entries.len() != selected_paths.len()
        || pages.len() != parsed_count
        || stored_examples as usize != expected_examples
        || stored_references as usize != expected_references
    {
        bail!("artifact row accounting mismatch");
    }
    Ok(())
}

pub(crate) fn artifact_metadata(conn: &Connection, key: &str) -> Result<String> {
    conn.query_row(
        "SELECT value FROM artifact_metadata WHERE key = ?1",
        [key],
        |row| row.get(0),
    )
    .with_context(|| format!("artifact metadata is missing: {key}"))
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

pub(crate) fn selected_page_ids(conn: &Connection, platform: &str) -> Result<Vec<String>> {
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

pub(crate) fn process_peak_memory_bytes() -> Option<u64> {
    #[cfg(target_os = "linux")]
    {
        let status = fs::read_to_string("/proc/self/status").ok()?;
        let kilobytes = status
            .lines()
            .find_map(|line| line.strip_prefix("VmHWM:"))?
            .split_whitespace()
            .next()?
            .parse::<u64>()
            .ok()?;
        return Some(kilobytes.saturating_mul(1024));
    }

    #[cfg(any(target_os = "macos", target_os = "ios"))]
    {
        let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
        // SAFETY: getrusage initializes the provided rusage structure on success.
        let result = unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) };
        if result == 0 {
            // macOS reports ru_maxrss in bytes; Linux is handled above and reports KiB.
            return Some(unsafe { usage.assume_init() }.ru_maxrss as u64);
        }
    }

    None
}

fn hardware_label() -> String {
    if let Some(label) = std::env::var_os("ASKMAN_BUILD_HARDWARE") {
        let label = label.to_string_lossy().trim().to_string();
        if !label.is_empty() {
            return label;
        }
    }

    #[cfg(target_os = "macos")]
    if let Ok(output) = std::process::Command::new("sysctl")
        .args(["-n", "hw.model"])
        .output()
        && output.status.success()
    {
        let model = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !model.is_empty() {
            return format!("{model} (macOS {})", std::env::consts::ARCH);
        }
    }

    #[cfg(target_os = "linux")]
    if let Ok(model) = fs::read_to_string("/sys/devices/virtual/dmi/id/product_name") {
        let model = model.trim();
        if !model.is_empty() {
            return format!("{model} (Linux {})", std::env::consts::ARCH);
        }
    }

    format!("{} {}", std::env::consts::OS, std::env::consts::ARCH)
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
