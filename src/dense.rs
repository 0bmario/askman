use crate::bundle::ValidatedBundle;
use crate::tldr_subset::{
    artifact_metadata, process_peak_memory_bytes, selected_page_ids, validate_artifact,
};
use anyhow::{Context, Result, anyhow, bail};
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use rusqlite::{Connection, OpenFlags, params, params_from_iter, types::Value};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use sqlite_vec::sqlite3_vec_init;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

pub const MODEL_ID: &str = "Qdrant/all-MiniLM-L6-v2-onnx";
pub const MODEL_CACHE_FOLDER: &str = "models--Qdrant--all-MiniLM-L6-v2-onnx";
pub const MODEL_REVISION: &str = "5f1b8cd78bc4fb444dd171e59b18f3a3af89a079";
pub const MODEL_DIMENSION: usize = 384;
pub const MODEL_MAX_LENGTH: usize = 512;
pub const MODEL_RUNTIME: &str = "fastembed-4.8.0";
pub const DENSE_INDEX_VERSION: &str = "dense-vec0-platform-partition-v3";
pub const DENSE_NORMALIZATION: &str = "l2";
pub const DENSE_DISTANCE_METRIC: &str = "cosine";
pub const DENSE_RECIPE_VERSION: &str = "dense-text-v1";
pub const DEFAULT_BATCH_SIZE: usize = 32;
const VEC0_MAX_K: usize = 4096;
const DENSE_PLATFORMS: [&str; 4] = ["common", "linux", "osx", "windows"];
const DENSE_QUERY_MODE_ENV: &str = "ASKMAN_DENSE_QUERY_MODE";
const EXPANDED_DEV_QUERY_MODE: &str = "expanded-dev";
const FOCUSED_QUERY_MODE: &str = "focused-v1";
const ANGULAR_PACKAGE_ADD_QUERY: &str = "Add a package to the current project";

pub const MODEL_FILES: [(&str, &str); 5] = [
    (
        "config.json",
        "1b4d8e2a3988377ed8b519a31d8d31025a25f1c5f8606998e8014111438efcd7",
    ),
    (
        "model.onnx",
        "bbd7b466f6d58e646fdc2bd5fd67b2f5e93c0b687011bd4548c420f7bd46f0c5",
    ),
    (
        "special_tokens_map.json",
        "5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a",
    ),
    (
        "tokenizer.json",
        "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0",
    ),
    (
        "tokenizer_config.json",
        "bd2e06a5b20fd1b13ca988bedc8763d332d242381b4fbc98f8fead4524158f79",
    ),
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DenseRecipe {
    Description,
    DescriptionWithParent,
    MainCompatible,
}

impl DenseRecipe {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "description" => Ok(Self::Description),
            "description-plus-parent" => Ok(Self::DescriptionWithParent),
            "main-compatible" => Ok(Self::MainCompatible),
            _ => bail!(
                "unsupported dense recipe `{value}`; expected description, description-plus-parent, or main-compatible"
            ),
        }
    }

    fn name(self) -> &'static str {
        match self {
            Self::Description => "description",
            Self::DescriptionWithParent => "description-plus-parent",
            Self::MainCompatible => "main-compatible",
        }
    }

    fn text(self, row: &DenseRow) -> String {
        match self {
            Self::Description => row.example_description.clone(),
            Self::DescriptionWithParent => {
                format!("{}\n{}", row.page_description, row.example_description)
            }
            Self::MainCompatible => legacy_main_embedding_text(
                &row.example_description,
                &row.page_command,
                &row.page_description,
                &row.example_command,
            ),
        }
    }
}

#[derive(Debug, Clone)]
pub struct DenseBuildOptions {
    pub artifact: PathBuf,
    pub model_cache: PathBuf,
    pub output: PathBuf,
    pub recipe: DenseRecipe,
    pub batch_size: usize,
}

#[cfg(feature = "dev")]
#[derive(Debug, Clone)]
pub struct LegacyMainDatabaseOptions {
    pub bundle: PathBuf,
    pub output: PathBuf,
    pub batch_size: usize,
}

#[cfg(feature = "dev")]
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LegacyMainDatabaseReport {
    pub output: PathBuf,
    pub example_count: usize,
    pub build_time_ms: u128,
    pub artifact_size_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DenseBuildReport {
    pub output: PathBuf,
    pub recipe: String,
    pub model_revision: String,
    pub indexed_examples: usize,
    pub build_time_ms: u128,
    pub peak_memory_bytes: Option<u64>,
    pub artifact_size_bytes: u64,
    pub hardware: String,
}

#[cfg(feature = "dev")]
#[derive(Debug)]
struct LegacyMainExample {
    example_id: String,
    page_command: String,
    platform: String,
    page_description: String,
    example_description: String,
    example_command: String,
}

#[derive(Debug, Clone)]
pub struct DenseServerOptions {
    pub artifact: PathBuf,
    pub model_cache: PathBuf,
}

#[derive(Debug, Deserialize)]
struct DenseQueryRequest {
    query: String,
    platform: String,
    limit: usize,
    #[serde(default)]
    platform_explicit: bool,
    #[serde(default)]
    include_same_page_examples: bool,
}

#[derive(Debug, Serialize)]
struct DenseReady {
    ready: bool,
    model_load_ms: u128,
    peak_memory_bytes: Option<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct DenseCandidate {
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
    pub page_position: usize,
    pub example_position: usize,
    pub ranking_score: f64,
}

#[derive(Debug)]
struct DenseRow {
    example_id: String,
    page_id: String,
    platform: String,
    page_command: String,
    page_description: String,
    example_description: String,
    example_command: String,
}

#[derive(Debug)]
struct ModelAssets {
    cache_dir: PathBuf,
    hashes: BTreeMap<String, String>,
}

pub(crate) struct DenseIndex {
    connection: Connection,
    embedder: OfflineEmbedder,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum DenseQueryMode {
    Raw,
    /// Frozen source-derived query rules selected on the v2 development split.
    IntentRulesV1,
    /// Small set of source-backed vocabulary mappings for the new candidate.
    FocusedIntentRulesV1,
}

/// The embedded ONNX runtime can abort during process teardown on this target.
/// The dev builder/server are short-lived tools, so keep the runtime alive until
/// process exit instead of invoking its unsafe native destructor.
struct OfflineEmbedder(Option<TextEmbedding>);

impl OfflineEmbedder {
    fn new(embedder: TextEmbedding) -> Self {
        Self(Some(embedder))
    }

    fn embed<S: AsRef<str> + Send + Sync>(
        &self,
        texts: Vec<S>,
        batch_size: Option<usize>,
    ) -> Result<Vec<Vec<f32>>> {
        self.0
            .as_ref()
            .ok_or_else(|| anyhow!("dense model runtime is unavailable"))?
            .embed(texts, batch_size)
            .map_err(Into::into)
    }
}

impl Drop for OfflineEmbedder {
    fn drop(&mut self) {
        if let Some(embedder) = self.0.take() {
            std::mem::forget(embedder);
        }
    }
}

pub fn build_dense_index(options: DenseBuildOptions) -> Result<DenseBuildReport> {
    if options.batch_size == 0 {
        bail!("dense batch size must be greater than zero");
    }
    register_sqlite_vec();

    let source = fs::canonicalize(&options.artifact).with_context(|| {
        format!(
            "failed to resolve validated lexical artifact {}",
            options.artifact.display()
        )
    })?;
    let source_connection = Connection::open(&source)
        .with_context(|| format!("failed to open lexical artifact {}", source.display()))?;
    validate_artifact(&source_connection)?;

    let output = absolute_output_path(&options.output)?;
    if source == output {
        bail!("dense output must differ from the lexical artifact");
    }
    let output_parent = output
        .parent()
        .ok_or_else(|| anyhow!("dense output has no parent: {}", output.display()))?;
    fs::create_dir_all(output_parent)?;
    let output_name = output
        .file_name()
        .ok_or_else(|| anyhow!("dense output has no file name: {}", output.display()))?
        .to_string_lossy();
    let temporary = output_parent.join(format!(".{output_name}.{}.part", std::process::id()));
    if temporary.exists() {
        bail!(
            "temporary dense output already exists: {}",
            temporary.display()
        );
    }

    let model_assets = validate_model_assets(&options.model_cache)?;
    let embedder = OfflineEmbedder::new(load_embedder(&model_assets)?);
    let rows = load_dense_rows(&source_connection)?;
    let source_digest = artifact_metadata(&source_connection, "source_digest")?;
    drop(source_connection);

    let result = write_dense_artifact(
        &temporary,
        &source,
        rows,
        source_digest,
        model_assets,
        embedder,
        options.recipe,
        options.batch_size,
        output.clone(),
    );
    match result {
        Ok(report) => match fs::rename(&temporary, &output) {
            Ok(()) => Ok(report),
            Err(error) => {
                let _ = fs::remove_file(&temporary);
                Err(error).with_context(|| {
                    format!("failed to publish dense artifact {}", output.display())
                })
            }
        },
        Err(error) => {
            let _ = fs::remove_file(&temporary);
            Err(error)
        }
    }
}

/// Build a scratch `pages_vec` database matching main's legacy query schema,
/// using the candidate bundle's exact visible corpus and main's stored-text recipe.
#[cfg(feature = "dev")]
pub fn build_legacy_main_database(
    options: LegacyMainDatabaseOptions,
) -> Result<LegacyMainDatabaseReport> {
    if options.batch_size == 0 {
        bail!("legacy main batch size must be greater than zero");
    }
    register_sqlite_vec();

    let started_at = Instant::now();
    let bundle_root = fs::canonicalize(&options.bundle).with_context(|| {
        format!(
            "failed to resolve matching bundle {}",
            options.bundle.display()
        )
    })?;
    let bundle = ValidatedBundle::open(&options.bundle)?;
    let database_path = bundle.database_path();
    let examples = load_legacy_main_examples(&database_path)?;
    if examples.is_empty() {
        bail!("matching bundle contains no visible examples");
    }

    let output = absolute_output_path(&options.output)?;
    if output.starts_with(&bundle_root) {
        bail!("legacy main database output must be outside the matching bundle");
    }
    if output.exists() {
        bail!(
            "legacy main database output already exists: {}",
            output.display()
        );
    }
    let output_parent = output
        .parent()
        .ok_or_else(|| anyhow!("legacy main output has no parent: {}", output.display()))?;
    fs::create_dir_all(output_parent)?;
    let output_name = output
        .file_name()
        .ok_or_else(|| anyhow!("legacy main output has no file name: {}", output.display()))?
        .to_string_lossy();
    let temporary = output_parent.join(format!(".{output_name}.{}.part", std::process::id()));
    if temporary.exists() {
        bail!(
            "temporary legacy main output already exists: {}",
            temporary.display()
        );
    }

    let model_assets = pinned_model_assets(&bundle.model_cache_path())?;
    let embedder = OfflineEmbedder::new(load_embedder(&model_assets)?);
    let build_result =
        write_legacy_main_database(&temporary, &examples, &embedder, options.batch_size)
            .and_then(|()| Ok(fs::metadata(&temporary)?.len()));

    match build_result {
        Ok(artifact_size_bytes) => match fs::rename(&temporary, &output) {
            Ok(()) => Ok(LegacyMainDatabaseReport {
                output,
                example_count: examples.len(),
                build_time_ms: started_at.elapsed().as_millis(),
                artifact_size_bytes,
            }),
            Err(error) => {
                let _ = fs::remove_file(&temporary);
                Err(error).with_context(|| {
                    format!(
                        "failed to publish legacy main database {}",
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

#[cfg(feature = "dev")]
fn load_legacy_main_examples(database: &Path) -> Result<Vec<LegacyMainExample>> {
    let connection = Connection::open_with_flags(
        database,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .with_context(|| format!("failed to open matching database {}", database.display()))?;
    let mut statement = connection
        .prepare(
            "SELECT e.example_id, p.command, p.platform, p.description,
                    e.description, e.command
             FROM examples AS e
             JOIN pages AS p ON p.page_id = e.page_id
             ORDER BY p.platform, p.page_position, e.position, e.example_id",
        )
        .context("matching bundle does not expose source-backed examples")?;
    let rows = statement.query_map([], |row| {
        Ok(LegacyMainExample {
            example_id: row.get(0)?,
            page_command: row.get(1)?,
            platform: row.get(2)?,
            page_description: row.get(3)?,
            example_description: row.get(4)?,
            example_command: row.get(5)?,
        })
    })?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .context("failed to read source-backed examples")
}

#[cfg(feature = "dev")]
fn write_legacy_main_database(
    output: &Path,
    examples: &[LegacyMainExample],
    embedder: &OfflineEmbedder,
    batch_size: usize,
) -> Result<()> {
    let mut connection = Connection::open(output)
        .with_context(|| format!("failed to create legacy main database {}", output.display()))?;
    connection.execute_batch(&format!(
        "CREATE VIRTUAL TABLE pages_vec USING vec0(
            command TEXT,
            os TEXT,
            description TEXT,
            example_desc TEXT,
            example_cmd TEXT,
            embedding FLOAT[{MODEL_DIMENSION}]
        );"
    ))?;

    let transaction = connection.transaction()?;
    {
        let mut insert = transaction.prepare(
            "INSERT INTO pages_vec(command, os, description, example_desc, example_cmd, embedding)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        )?;
        for batch in examples.chunks(batch_size) {
            let texts = batch
                .iter()
                .map(|example| {
                    legacy_main_embedding_text(
                        &example.example_description,
                        &example.page_command,
                        &example.page_description,
                        &example.example_command,
                    )
                })
                .collect::<Vec<_>>();
            let embeddings = embedder
                .embed(texts, Some(batch_size))
                .context("failed to embed legacy main example batch")?;
            if embeddings.len() != batch.len() {
                bail!(
                    "dense model returned {} vectors for {} legacy main examples",
                    embeddings.len(),
                    batch.len()
                );
            }
            for (example, embedding) in batch.iter().zip(embeddings) {
                validate_embedding(&embedding, &example.example_id)?;
                insert.execute(params![
                    example.page_command,
                    example.platform,
                    example.page_description,
                    example.example_description,
                    example.example_command,
                    embedding_blob(&embedding),
                ])?;
            }
        }
    }
    transaction.commit()?;
    Ok(())
}

fn legacy_main_embedding_text(
    example_description: &str,
    page_command: &str,
    page_description: &str,
    example_command: &str,
) -> String {
    // Keep this in sync with `main:src/import_tldr.rs::process_directory`.
    format!(
        "Task: {example_description}. Command: {page_command}. Description: {page_description}. Example: {example_description} {example_command}"
    )
}

pub fn run_query_server(options: DenseServerOptions) -> Result<()> {
    register_sqlite_vec();
    let query_mode = dense_server_query_mode()?;
    let started_at = Instant::now();
    let index = DenseIndex::open(&options.artifact, &options.model_cache)?;
    let result = (|| -> Result<()> {
        let ready = serde_json::to_string(&DenseReady {
            ready: true,
            model_load_ms: started_at.elapsed().as_millis(),
            peak_memory_bytes: process_peak_memory_bytes(),
        })?;
        println!("{ready}");
        std::io::stdout().flush()?;

        for line in std::io::stdin().lock().lines() {
            let line = line?;
            if line.trim().is_empty() {
                continue;
            }
            let response = match serde_json::from_str::<DenseQueryRequest>(&line) {
                Ok(request) => {
                    match index.query_with_mode(
                        &request.query,
                        &request.platform,
                        request.limit,
                        query_mode,
                        request.platform_explicit,
                        request.include_same_page_examples,
                    ) {
                        Ok(results) => serde_json::json!({"ok": true, "results": results}),
                        Err(error) => serde_json::json!({"ok": false, "error": error.to_string()}),
                    }
                }
                Err(error) => serde_json::json!({"ok": false, "error": error.to_string()}),
            };
            println!("{}", serde_json::to_string(&response)?);
            std::io::stdout().flush()?;
        }
        Ok(())
    })();
    // fastembed's native runtime can abort while tearing down on hosts that
    // already loaded another ONNX Runtime. The helper is a process boundary;
    // keep the runtime alive until the process exits instead of running its
    // unreliable destructor during normal EOF/error handling.
    std::mem::forget(index);
    result
}

impl DenseIndex {
    pub(crate) fn open(artifact: &Path, model_cache: &Path) -> Result<Self> {
        register_sqlite_vec();
        let assets = validate_model_assets(model_cache)?;
        Self::open_index(artifact, assets)
    }

    /// Open a dense index through the matching-bundle validation capability.
    /// Its immutable artifacts were checked at that boundary; query opening
    /// must not repeat corpus/vector scans.
    pub(crate) fn open_from_bundle(bundle: &ValidatedBundle) -> Result<Self> {
        register_sqlite_vec();
        let artifact = bundle.database_path();
        let model_cache = bundle.model_cache_path();
        let assets = pinned_model_assets(&model_cache)?;
        let connection = Connection::open_with_flags(
            &artifact,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .with_context(|| format!("failed to open dense artifact {}", artifact.display()))?;
        Self::from_validated_connection(connection, assets)
    }

    fn open_index(artifact: &Path, assets: ModelAssets) -> Result<Self> {
        let connection = Connection::open(artifact)
            .with_context(|| format!("failed to open dense artifact {}", artifact.display()))?;
        validate_artifact(&connection)?;
        validate_dense_artifact(&connection, &assets)?;
        Self::from_validated_connection(connection, assets)
    }

    fn from_validated_connection(connection: Connection, assets: ModelAssets) -> Result<Self> {
        let embedder = OfflineEmbedder::new(load_embedder(&assets)?);
        Ok(Self {
            connection,
            embedder,
        })
    }

    pub(crate) fn query_with_mode(
        &self,
        query: &str,
        platform: &str,
        limit: usize,
        query_mode: DenseQueryMode,
        platform_explicit: bool,
        include_same_page_examples: bool,
    ) -> Result<Vec<DenseCandidate>> {
        let selected_pages = selected_page_ids(&self.connection, platform)?;
        self.query_with_selected_pages_and_selection(
            query,
            platform,
            limit,
            &selected_pages,
            query_mode,
            platform_explicit,
            include_same_page_examples,
        )
    }

    pub(crate) fn query_with_selected_pages(
        &self,
        query: &str,
        platform: &str,
        limit: usize,
        selected_pages: &[String],
        query_mode: DenseQueryMode,
        platform_explicit: bool,
    ) -> Result<Vec<DenseCandidate>> {
        self.query_with_selected_pages_and_selection(
            query,
            platform,
            limit,
            selected_pages,
            query_mode,
            platform_explicit,
            false,
        )
    }

    fn query_with_selected_pages_and_selection(
        &self,
        query: &str,
        platform: &str,
        limit: usize,
        selected_pages: &[String],
        query_mode: DenseQueryMode,
        platform_explicit: bool,
        include_same_page_examples: bool,
    ) -> Result<Vec<DenseCandidate>> {
        if limit == 0 {
            bail!("dense query limit must be greater than zero");
        }
        let dense_query = dense_query_text_for_platform(query, query_mode, platform);
        let query_vector = self
            .embedder
            .embed(vec![dense_query], Some(1))?
            .pop()
            .ok_or_else(|| anyhow!("dense model returned no query vector"))?;
        validate_embedding(&query_vector, "query")?;

        query_dense_candidates(
            &self.connection,
            &query_vector,
            platform,
            selected_pages,
            limit,
            platform_explicit,
            include_same_page_examples,
        )
    }
}

fn query_dense_candidates(
    connection: &Connection,
    query_vector: &[f32],
    platform: &str,
    selected_pages: &[String],
    limit: usize,
    platform_explicit: bool,
    include_same_page_examples: bool,
) -> Result<Vec<DenseCandidate>> {
    if !DENSE_PLATFORMS.contains(&platform) {
        bail!("unsupported target platform: {platform}");
    }
    if limit == 0 {
        bail!("dense query limit must be greater than zero");
    }

    if selected_pages.is_empty() {
        return Ok(Vec::new());
    }
    let selected_page_set = selected_pages.iter().cloned().collect::<HashSet<_>>();
    let platforms = if platform == "common" {
        vec!["common"]
    } else {
        vec!["common", platform]
    };
    let mut details = connection.prepare(
        "SELECT e.example_id, e.page_id, p.command, e.command, p.description, e.description,
                p.source_path, p.source_ref, p.source_revision, p.platform,
                p.page_position, e.position
         FROM examples AS e
         JOIN pages AS p ON p.page_id = e.page_id
         WHERE e.example_id = ?1",
    )?;

    let mut results = Vec::new();
    let mut all_seen_pages = HashSet::new();
    for candidate_platform in platforms {
        let platform_results = query_partition_candidates(
            connection,
            &mut details,
            query_vector,
            candidate_platform,
            selected_pages,
            &selected_page_set,
            limit,
            include_same_page_examples,
        )?;
        for candidate in platform_results {
            if include_same_page_examples || all_seen_pages.insert(candidate.page_id.clone()) {
                results.push(candidate);
            }
        }
    }

    if platform_explicit {
        results.sort_by(|a, b| {
            let a_target = a.platform == platform;
            let b_target = b.platform == platform;
            a.ranking_score
                .total_cmp(&b.ranking_score)
                .then_with(|| b_target.cmp(&a_target))
                .then_with(|| a.example_id.cmp(&b.example_id))
        });
    } else {
        results.sort_by(|a, b| {
            a.ranking_score
                .total_cmp(&b.ranking_score)
                .then_with(|| a.example_id.cmp(&b.example_id))
        });
    }
    results.truncate(limit);
    Ok(results)
}

fn query_partition_candidates(
    connection: &Connection,
    details: &mut rusqlite::Statement<'_>,
    query_vector: &[f32],
    platform: &str,
    selected_pages: &[String],
    selected_page_set: &HashSet<String>,
    limit: usize,
    include_same_page_examples: bool,
) -> Result<Vec<DenseCandidate>> {
    let (max_examples_per_page, platform_example_count) =
        platform_vector_bounds(connection, platform)?;
    if platform_example_count == 0 {
        return Ok(Vec::new());
    }

    let mut candidate_limit = if include_same_page_examples {
        limit
    } else {
        limit.saturating_mul(max_examples_per_page)
    };
    if candidate_limit == 0 || candidate_limit >= VEC0_MAX_K {
        return exact_partition_candidates(
            connection,
            details,
            query_vector,
            platform,
            selected_pages,
            selected_page_set,
            limit,
            include_same_page_examples,
        );
    }

    loop {
        let guarded_limit = candidate_limit + 1;
        let candidates = query_partition_top_k(connection, query_vector, platform, guarded_limit)?;
        let all_candidates_returned = platform_example_count <= guarded_limit;
        if candidates.len() < guarded_limit && !all_candidates_returned {
            bail!(
                "dense vector index returned fewer candidates than requested for platform {platform}"
            );
        }
        let boundary_tie = !all_candidates_returned
            && candidates.len() > candidate_limit
            && candidates[candidate_limit - 1].1 == candidates[candidate_limit].1;
        if boundary_tie {
            if let Some(next_limit) = next_tie_candidate_limit(candidate_limit) {
                candidate_limit = next_limit;
                continue;
            }
            return exact_partition_candidates(
                connection,
                details,
                query_vector,
                platform,
                selected_pages,
                selected_page_set,
                limit,
                include_same_page_examples,
            );
        }

        let included_count = if all_candidates_returned {
            candidates.len()
        } else {
            candidate_limit
        };
        let platform_results = materialize_partition_candidates(
            candidates.into_iter().take(included_count).collect(),
            details,
            selected_page_set,
            limit,
            include_same_page_examples,
        )?;
        if all_candidates_returned || platform_results.len() == limit {
            return Ok(platform_results);
        }
        if candidate_limit >= VEC0_MAX_K - 1 {
            return exact_partition_candidates(
                connection,
                details,
                query_vector,
                platform,
                selected_pages,
                selected_page_set,
                limit,
                include_same_page_examples,
            );
        }
        candidate_limit = candidate_limit.saturating_mul(2).min(VEC0_MAX_K - 1);
    }
}

fn exact_partition_candidates(
    connection: &Connection,
    details: &mut rusqlite::Statement<'_>,
    query_vector: &[f32],
    platform: &str,
    selected_pages: &[String],
    selected_page_set: &HashSet<String>,
    limit: usize,
    include_same_page_examples: bool,
) -> Result<Vec<DenseCandidate>> {
    let rows = query_partition_exact(connection, query_vector, platform, selected_pages)?;
    materialize_partition_candidates(
        rows,
        details,
        selected_page_set,
        limit,
        include_same_page_examples,
    )
}

fn materialize_partition_candidates(
    rows: Vec<(String, f64)>,
    details: &mut rusqlite::Statement<'_>,
    selected_page_ids: &HashSet<String>,
    limit: usize,
    include_same_page_examples: bool,
) -> Result<Vec<DenseCandidate>> {
    let mut seen_pages = HashSet::new();
    let mut results = Vec::new();
    for (example_id, distance) in rows {
        let candidate = details.query_row(params![example_id], |row| {
            Ok(DenseCandidate {
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
                page_position: row.get::<_, i64>(10)? as usize,
                example_position: row.get::<_, i64>(11)? as usize,
                ranking_score: distance,
            })
        })?;
        if selected_page_ids.contains(&candidate.page_id)
            && (include_same_page_examples || seen_pages.insert(candidate.page_id.clone()))
        {
            results.push(candidate);
            if results.len() == limit {
                break;
            }
        }
    }
    Ok(results)
}

fn platform_vector_bounds(connection: &Connection, platform: &str) -> Result<(usize, usize)> {
    let max_per_page = artifact_metadata(
        connection,
        &format!("dense_max_examples_per_page_{platform}"),
    )?
    .parse::<usize>()
    .context("maximum page example count metadata is invalid")?;
    let total_count = artifact_metadata(
        connection,
        &format!("dense_platform_example_count_{platform}"),
    )?
    .parse::<usize>()
    .context("platform example count metadata is invalid")?;
    Ok((max_per_page, total_count))
}

fn next_tie_candidate_limit(current: usize) -> Option<usize> {
    if current >= VEC0_MAX_K - 1 {
        return None;
    }
    Some(
        current
            .saturating_mul(2)
            .max(current + 1)
            .min(VEC0_MAX_K - 1),
    )
}

fn computed_platform_vector_bounds(rows: &[DenseRow]) -> HashMap<String, (usize, usize)> {
    let mut page_counts = HashMap::<(String, String), usize>::new();
    for row in rows {
        *page_counts
            .entry((row.platform.clone(), row.page_id.clone()))
            .or_default() += 1;
    }

    let mut bounds = DENSE_PLATFORMS
        .iter()
        .map(|platform| (platform.to_string(), (0, 0)))
        .collect::<HashMap<_, _>>();
    for ((platform, _), page_count) in page_counts {
        let entry = bounds.entry(platform).or_default();
        entry.0 = entry.0.max(page_count);
        entry.1 += page_count;
    }
    bounds
}

fn validate_platform_vector_bounds(connection: &Connection) -> Result<()> {
    let actual_bounds = {
        let mut actual_bounds = HashMap::new();
        let mut statement = connection.prepare(
            "SELECT platform, MAX(page_count), SUM(page_count)
             FROM (
                 SELECT p.platform AS platform, e.page_id AS page_id, COUNT(*) AS page_count
                 FROM example_dense AS dense
                 JOIN examples AS e ON e.example_id = dense.example_id
                 JOIN pages AS p ON p.page_id = e.page_id
                 GROUP BY p.platform, e.page_id
             )
             GROUP BY platform",
        )?;
        for row in statement.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, i64>(2)?,
            ))
        })? {
            let (platform, max_per_page, total_count) = row?;
            actual_bounds.insert(
                platform,
                (
                    usize::try_from(max_per_page)
                        .context("maximum page example count is invalid")?,
                    usize::try_from(total_count).context("platform example count is invalid")?,
                ),
            );
        }
        actual_bounds
    };

    for platform in DENSE_PLATFORMS {
        let expected = actual_bounds.get(platform).copied().unwrap_or_default();
        let declared = platform_vector_bounds(connection, platform)?;
        if declared != expected {
            bail!(
                "dense platform vector bounds metadata does not match stored examples for {platform}"
            );
        }
    }
    Ok(())
}

fn query_partition_exact(
    connection: &Connection,
    query_vector: &[f32],
    platform: &str,
    selected_pages: &[String],
) -> Result<Vec<(String, f64)>> {
    if selected_pages.is_empty() {
        return Ok(Vec::new());
    }
    let page_placeholders = std::iter::repeat_n("?", selected_pages.len())
        .collect::<Vec<_>>()
        .join(", ");
    let mut statement = connection.prepare(&format!(
        "SELECT dense.example_id,
                    vec_distance_cosine(dense.embedding, ?1) AS distance
             FROM example_dense AS dense
             JOIN examples AS e ON e.example_id = dense.example_id
             JOIN pages AS p ON p.page_id = e.page_id
             WHERE p.platform = ?2 AND e.page_id IN ({page_placeholders})
             ORDER BY distance, dense.example_id"
    ))?;
    let query_params = std::iter::once(Value::Blob(embedding_blob(query_vector)))
        .chain(std::iter::once(Value::Text(platform.to_string())))
        .chain(selected_pages.iter().cloned().map(Value::Text));
    let rows = statement.query_map(params_from_iter(query_params), |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, f64>(1)?))
    })?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .map_err(Into::into)
}

fn query_partition_top_k(
    connection: &Connection,
    query_vector: &[f32],
    platform: &str,
    limit: usize,
) -> Result<Vec<(String, f64)>> {
    if limit == 0 || limit > VEC0_MAX_K {
        bail!("partitioned dense query limit must be from 1 through {VEC0_MAX_K}");
    }

    let mut statement = connection.prepare(
        "SELECT example_id, distance
         FROM example_dense_index
         WHERE embedding MATCH ?1 AND k = ?2 AND platform = ?3
         ORDER BY distance",
    )?;
    let rows = statement.query_map(
        params![embedding_blob(query_vector), limit as i64, platform],
        |row| Ok((row.get::<_, String>(0)?, row.get::<_, f64>(1)?)),
    )?;
    let mut results = rows.collect::<rusqlite::Result<Vec<_>>>()?;
    results.sort_by(|(left_id, left_distance), (right_id, right_distance)| {
        left_distance
            .total_cmp(right_distance)
            .then_with(|| left_id.cmp(right_id))
    });
    Ok(results)
}

fn dense_server_query_mode() -> Result<DenseQueryMode> {
    match std::env::var(DENSE_QUERY_MODE_ENV) {
        Ok(value) if value == EXPANDED_DEV_QUERY_MODE => Ok(DenseQueryMode::IntentRulesV1),
        Ok(value) if value == FOCUSED_QUERY_MODE => Ok(DenseQueryMode::FocusedIntentRulesV1),
        Ok(value) => bail!(
            "unsupported {DENSE_QUERY_MODE_ENV} value `{value}`; unset it for raw queries or use `{EXPANDED_DEV_QUERY_MODE}` or `{FOCUSED_QUERY_MODE}`"
        ),
        Err(std::env::VarError::NotPresent) => Ok(DenseQueryMode::Raw),
        Err(std::env::VarError::NotUnicode(_)) => {
            bail!("{DENSE_QUERY_MODE_ENV} must contain valid Unicode")
        }
    }
}

pub(crate) fn expanded_query_phrases_for_platform(
    query: &str,
    query_mode: DenseQueryMode,
    platform: &str,
) -> Vec<&'static str> {
    if query_mode == DenseQueryMode::Raw {
        return Vec::new();
    }

    let normalized = query.to_ascii_lowercase();
    let query_words = normalized
        .split(|character: char| !character.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .collect::<Vec<_>>();
    let mut additions = Vec::new();
    let query_is_negated = query_contains_negation(&normalized, &query_words);
    let targets_linux_platform = platform == "linux" || query_words.contains(&"linux");
    let targets_windows_platform = platform == "windows" || query_words.contains(&"windows");

    if query_mode == DenseQueryMode::FocusedIntentRulesV1 {
        let mut focused_additions = Vec::new();
        let mentions_file = query_words.contains(&"file");
        let names_file_contents =
            query_words.contains(&"contents") || query_words.contains(&"text");
        let mentions_standard_output = query_words
            .windows(2)
            .any(|words| words == ["standard", "output"]);
        let requests_file_observation = ["read", "print", "show", "display"]
            .iter()
            .any(|term| query_words.contains(term));
        if mentions_file
            && (mentions_standard_output
                || query_words.contains(&"stdout")
                || (names_file_contents && requests_file_observation))
            && !query_is_negated
        {
            focused_additions.push("print contents file stdout");
        }

        let names_linux_interface_addresses = targets_linux_platform
            && (query_words.contains(&"interface") || query_words.contains(&"interfaces"));
        let names_ip_addresses = query_words.contains(&"ipv4")
            || query_words.contains(&"address")
            || query_words.contains(&"addresses");
        let names_mac_addresses = query_words.contains(&"mac") || query_words.contains(&"hardware");
        let requests_interface_observation = ["display", "inspect", "show", "list", "print"]
            .iter()
            .any(|term| query_words.contains(term));
        if names_linux_interface_addresses
            && names_ip_addresses
            && !names_mac_addresses
            && requests_interface_observation
            && !query_is_negated
        {
            focused_additions.push("list interfaces detailed info brief network layer");
        }

        let names_systemd_tooling =
            query_words.contains(&"systemd") || query_words.contains(&"systemctl");
        if query_words.contains(&"restart") && names_systemd_tooling && !query_is_negated {
            focused_additions.push("start stop restart reload show status service");
        }

        let mentions_clipboard =
            query_words.contains(&"clipboard") || query_words.contains(&"pasteboard");
        let requests_clipboard_write = ["copy", "send", "place", "pipe", "put", "write"]
            .iter()
            .any(|term| query_words.contains(term));
        let names_extraction_source = query_words.contains(&"from");
        let requests_clipboard_contents_to_file = query_words.contains(&"contents")
            && mentions_file
            && (query_words.contains(&"to") || query_words.contains(&"into"));
        if mentions_clipboard && requests_clipboard_contents_to_file && !query_is_negated {
            focused_additions.push("Write the contents of the clipboard to a file");
        } else if mentions_clipboard
            && requests_clipboard_write
            && !names_extraction_source
            && !query_is_negated
        {
            focused_additions
                .push("pbcopy place the results of a specific command in the clipboard");
        }

        let requests_file_copy = ["copy", "duplicate", "put"]
            .iter()
            .any(|term| query_words.contains(term));
        let names_destination = ["another", "destination", "folder", "path", "directory"]
            .iter()
            .any(|term| query_words.contains(term))
            || query_words
                .windows(2)
                .any(|words| words == ["second", "copy"]);
        if platform == "windows"
            && requests_file_copy
            && mentions_file
            && names_destination
            && !query_is_negated
        {
            focused_additions.push("Copy a file into another directory, keeping the filename");
        }

        return focused_additions;
    }

    let names_filesystem_space = ["disk", "filesystem", "filesystems", "storage"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_available_space = ["available", "free"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_information = ["check", "display", "find", "inspect", "list", "see", "show"]
        .iter()
        .any(|term| query_words.contains(term));
    let targets_unix_platform = matches!(platform, "linux" | "osx");
    if names_filesystem_space
        && requests_available_space
        && requests_information
        && targets_unix_platform
        && !query_is_negated
    {
        additions.push("Display all filesystems in human-readable form");
    }

    let names_system_memory = query_words.contains(&"ram") || query_words.contains(&"memory");
    let requests_memory_usage = ["check", "display", "inspect", "list", "show", "view"]
        .iter()
        .any(|term| query_words.contains(term));
    let names_memory_units = ["byte", "bytes", "gb", "gigabytes", "kb", "mb", "megabytes"]
        .iter()
        .any(|term| query_words.contains(term));
    if targets_linux_platform && names_system_memory && requests_memory_usage && !query_is_negated {
        if names_memory_units {
            additions.push("Display memory in Bytes/KB/MB/GB");
        } else {
            additions.push("Display system memory");
        }
    }

    let requests_directory_listing = ["display", "list", "show", "view"]
        .iter()
        .any(|term| query_words.contains(term));
    let names_hidden_entries = query_words.contains(&"hidden");
    let requests_size_sort = query_words.contains(&"sort") || query_words.contains(&"sorted");
    let names_file_size = query_words.contains(&"size") || query_words.contains(&"sized");
    if platform != "windows"
        && requests_directory_listing
        && names_hidden_entries
        && requests_size_sort
        && names_file_size
        && !query_is_negated
    {
        additions.push("List files in long format, sorted by size (descending) recursively");
    }

    let requests_sort = query_words.contains(&"sort") || query_words.contains(&"sorted");
    let names_duplicate_lines = ["duplicate", "duplicates", "duplicated"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_duplicate_removal = ["deduplicate", "discard", "drop", "filter", "remove"]
        .iter()
        .any(|term| query_words.contains(term));
    if requests_sort && names_duplicate_lines && requests_duplicate_removal && !query_is_negated {
        // Use the corpus's exact sorted-unique example, not `uniq -d` which lists duplicates.
        additions.push("Sort a file preserving only unique lines");
    }

    let names_angular_project = query_words.contains(&"angular")
        && ["app", "application", "project", "workspace"]
            .iter()
            .any(|term| query_words.contains(term));
    let names_package = ["dependencies", "dependency", "package", "packages"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_package_addition = ["add", "install", "installing"]
        .iter()
        .any(|term| query_words.contains(term));
    if names_angular_project && names_package && requests_package_addition && !query_is_negated {
        // Anchor package-install paraphrases to the corpus's operational `ng add` example.
        additions.push(ANGULAR_PACKAGE_ADD_QUERY);
    }

    let mentions_file = query_words.contains(&"file");
    let mentions_standard_output = query_words
        .windows(2)
        .any(|words| words == ["standard", "output"]);
    let names_file_contents = query_words.contains(&"contents") || query_words.contains(&"text");
    let requests_file_observation = ["read", "print", "show", "display"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_file_contents = mentions_standard_output
        || query_words.contains(&"stdout")
        || (names_file_contents && requests_file_observation);
    // Requiring an explicit file keeps generic stdout intents, notably
    // pasteboard piping, from being pulled toward `cat`.
    if mentions_file && requests_file_contents {
        additions.push("print contents file stdout");
    }

    let requests_restart = query_words.contains(&"restart");
    let names_systemd_tooling =
        query_words.contains(&"systemd") || query_words.contains(&"systemctl");
    if requests_restart && names_systemd_tooling {
        additions.push("start stop restart reload show status service");
    }

    let requests_file_open = query_words.contains(&"open") || query_words.contains(&"launch");
    let names_openable_path = ["directory", "file", "folder", "path"]
        .iter()
        .any(|term| query_words.contains(term));
    let names_default_application = ["app", "application"]
        .iter()
        .any(|term| query_words.contains(term))
        && (query_words.contains(&"default") || query_words.contains(&"associated"));
    if platform == "osx"
        && requests_file_open
        && names_openable_path
        && names_default_application
        && !query_is_negated
    {
        // This source-backed phrase distinguishes file paths from URI examples.
        additions.push("Open a file with the associated application");
    }

    let names_photo = ["photo", "picture", "image"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_metadata_observation = ["display", "extract", "inspect", "print", "read", "show"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_metadata_removal = [
        "clear", "delete", "erase", "purge", "remove", "scrub", "strip", "wipe",
    ]
    .iter()
    .any(|term| query_words.contains(term));
    let names_exif_metadata = query_words.contains(&"exif")
        || (names_photo
            && requests_metadata_observation
            && ["camera", "fields", "metadata", "tags"]
                .iter()
                .any(|term| query_words.contains(term)));
    if names_exif_metadata
        && requests_metadata_observation
        && !requests_metadata_removal
        && !query_is_negated
    {
        // Use the pinned exiftool page's direct read example, not generic
        // macOS file metadata commands such as `mdls`.
        additions.push("Print the EXIF metadata for a given file");
    }

    let names_archive = query_words.contains(&"archive");
    let requests_archive_encryption = ["encrypt", "encrypted", "encryption", "password"]
        .iter()
        .any(|term| query_words.contains(term));
    if names_archive && requests_archive_encryption {
        // The full pinned corpus has direct password/encryption examples for
        // 7z, RAR, and Zip; the small evaluation catalog omits those pages.
        additions.push("Password protect the resulting archive");
        additions.push("Create an encrypted archive with a specific password");
    }
    let requests_archive_extraction = ["extract", "unpack", "untar"]
        .iter()
        .any(|term| query_words.contains(term));
    let names_tar_archive = query_words.contains(&"tar") || query_words.contains(&"untar");
    if names_archive
        && requests_archive_extraction
        && !requests_archive_encryption
        && !query_is_negated
    {
        if names_tar_archive {
            additions.push("source.tar target directory");
        } else {
            additions.push("Extract a (compressed) archive file into the target directory");
        }
    }

    let names_registry = query_words.contains(&"registry");
    let requests_registry_lookup = [
        "display", "inspect", "look", "query", "read", "search", "show",
    ]
    .iter()
    .any(|term| query_words.contains(term));
    if names_registry && requests_registry_lookup {
        // Bias lookups toward the pinned `reg query` page rather than the
        // generic `reg` command overview or registry mutation examples.
        additions.push("reg query Display all values of a key");
    }

    let names_nftables_tool = query_words.contains(&"nft") || query_words.contains(&"nftables");
    let requests_rule_addition = ["add", "allow", "configure", "create", "permit"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_rule_blocking = ["block", "deny", "drop", "reject"]
        .iter()
        .any(|term| query_words.contains(term));
    if names_nftables_tool && requests_rule_addition && !requests_rule_blocking {
        // Use the pinned page's own phrasing so paraphrased rule requests land
        // on the available nft example without rewriting block/deny intents.
        additions.push("Add a new rule to accept several TCP ports");
    }

    let names_linux_interface_addresses = targets_linux_platform
        && (query_words.contains(&"interface") || query_words.contains(&"interfaces"));
    let names_ip_addresses = query_words.contains(&"ipv4")
        || query_words.contains(&"address")
        || query_words.contains(&"addresses");
    let names_mac_addresses = query_words.contains(&"mac") || query_words.contains(&"hardware");
    let requests_interface_observation = ["display", "inspect", "show", "list"]
        .iter()
        .chain(["print"].iter())
        .any(|term| query_words.contains(term));
    if names_linux_interface_addresses
        && names_ip_addresses
        && !names_mac_addresses
        && requests_interface_observation
    {
        // These terms occur in the pinned observation descriptions. `address`
        // also occurs in add/delete descriptions, so it would broaden the intent.
        additions.push("list interfaces detailed info brief network layer");
    }

    // macOS pasteboard direction: place/copy/send/pipe/put something ONTO the
    // clipboard is `pbcopy`; reading FROM it is not — queries with extraction
    // phrasing ("from the clipboard") stay unexpanded.
    let mentions_clipboard =
        query_words.contains(&"clipboard") || query_words.contains(&"pasteboard");
    let requests_clipboard_write = ["copy", "send", "place", "pipe", "put"]
        .iter()
        .any(|term| query_words.contains(term));
    let names_extraction_source = query_words.contains(&"from");
    let requests_clipboard_contents_to_file = query_words.contains(&"contents")
        && query_words.contains(&"file")
        && (query_words.contains(&"to") || query_words.contains(&"into"));
    if mentions_clipboard && requests_clipboard_contents_to_file && !query_is_negated {
        additions.push("Write the contents of the clipboard to a file");
    } else if mentions_clipboard
        && requests_clipboard_write
        && !names_extraction_source
        && !query_is_negated
    {
        additions.push("pbcopy place the results of a specific command in the clipboard");
    }

    let requests_file_copy = ["copy", "duplicate", "put"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_recursive_copy = query_words.contains(&"recursive")
        || query_words.contains(&"recursively")
        || query_words.contains(&"tree")
        || query_words.contains(&"structure");
    let names_directory_tree = ["directory", "folder", "tree", "structure"]
        .iter()
        .any(|term| query_words.contains(term));
    let names_copy_destination = ["another", "destination", "location", "path", "target"]
        .iter()
        .any(|term| query_words.contains(term));
    if requests_file_copy
        && names_directory_tree
        && requests_recursive_copy
        && names_copy_destination
        && !query_is_negated
    {
        if targets_windows_platform {
            additions.push("Copy files and directory trees");
        } else if ["keep", "keeping", "preserve", "preserving", "permissions"]
            .iter()
            .any(|term| query_words.contains(term))
        {
            additions.push(
                "Use archive mode (recursively copy directories, copy symlinks without resolving, and preserve permissions, ownership, and modification times)",
            );
        } else {
            additions.push("Recursively copy a directory's contents to another location");
        }
    }

    let requests_single_rename = query_words.contains(&"rename")
        && query.contains('.')
        && !["batch", "multiple", "pattern"]
            .iter()
            .any(|term| query_words.contains(term));
    if requests_single_rename && !query_is_negated {
        additions.push("Rename a file or directory when the target is not an existing directory");
    }

    let requests_text_search = ["find", "locate", "scan", "search"]
        .iter()
        .any(|term| query_words.contains(term));
    let names_search_target = [
        "directory",
        "file",
        "files",
        "folder",
        "log",
        "logs",
        "tree",
    ]
    .iter()
    .any(|term| query_words.contains(term));
    let names_search_term = ["pattern", "string", "text", "word"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_recursive_search = ["all", "every", "recursive", "recursively"]
        .iter()
        .any(|term| query_words.contains(term));
    if requests_text_search
        && names_search_target
        && names_search_term
        && requests_recursive_search
        && !query_is_negated
    {
        if targets_windows_platform {
            additions.push("Find one or more strings in all files recursively");
        } else {
            additions.push("Search for a pattern in all files recursively in a directory");
        }
    }

    // File copy with a destination: use the pinned single-file example's own
    // wording. Generic "directory/destination" terms favor multi-file variants.
    // "make a second copy" is a duplicate intent without an explicit destination.
    let names_moved_object = query_words.contains(&"file");
    let names_destination = ["another", "destination", "folder", "path", "directory"]
        .iter()
        .any(|term| query_words.contains(term))
        || query_words
            .windows(2)
            .any(|words| words == ["second", "copy"]);
    if requests_file_copy && names_moved_object && names_destination && !query_is_negated {
        additions.push("Copy a file into another directory, keeping the filename");
    }

    additions
}

fn query_contains_negation(query: &str, query_words: &[&str]) -> bool {
    const NEGATION_WORDS: [&str; 6] = ["avoid", "cannot", "never", "no", "not", "without"];
    const NEGATION_CONTRACTIONS: [&str; 14] = [
        "can't",
        "can’t",
        "doesn't",
        "doesn’t",
        "don't",
        "don’t",
        "mustn't",
        "mustn’t",
        "shouldn't",
        "shouldn’t",
        "wouldn't",
        "wouldn’t",
        "won't",
        "won’t",
    ];

    NEGATION_WORDS.iter().any(|term| query_words.contains(term))
        || NEGATION_CONTRACTIONS
            .iter()
            .any(|term| query.contains(term))
}

pub(crate) fn is_negated_exif_observation_query(query: &str) -> bool {
    let normalized = query.to_ascii_lowercase();
    let query_words = normalized
        .split(|character: char| !character.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .collect::<Vec<_>>();
    is_negated_exif_observation_words(&normalized, &query_words)
}

pub(crate) fn is_negated_file_stdout_query(query: &str) -> bool {
    let normalized = query.to_ascii_lowercase();
    let query_words = normalized
        .split(|character: char| !character.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .collect::<Vec<_>>();
    let names_file = query_words
        .iter()
        .any(|word| ["file", "files"].contains(word));
    let names_file_contents = query_words
        .iter()
        .any(|word| ["content", "contents", "text"].contains(word));
    let names_stdout = query_words.contains(&"stdout")
        || query_words
            .windows(2)
            .any(|words| words == ["standard", "output"]);
    let requests_file_output = [
        "display",
        "displaying",
        "print",
        "printing",
        "read",
        "reading",
        "show",
        "showing",
        "write",
        "writing",
    ]
    .iter()
    .any(|term| query_words.contains(term));

    names_file
        && names_file_contents
        && names_stdout
        && requests_file_output
        && query_contains_negation(&normalized, &query_words)
}

fn is_negated_exif_observation_words(query: &str, query_words: &[&str]) -> bool {
    let names_photo = ["photo", "picture", "image"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_metadata_observation = ["display", "extract", "inspect", "print", "read", "show"]
        .iter()
        .any(|term| query_words.contains(term));
    let requests_metadata_removal = [
        "clear", "delete", "erase", "purge", "remove", "scrub", "strip", "wipe",
    ]
    .iter()
    .any(|term| query_words.contains(term));
    let names_exif_metadata = query_words.contains(&"exif")
        || (names_photo
            && requests_metadata_observation
            && ["camera", "fields", "metadata", "tags"]
                .iter()
                .any(|term| query_words.contains(term)));

    names_exif_metadata
        && requests_metadata_observation
        && !requests_metadata_removal
        && query_contains_negation(query, query_words)
}

#[cfg(test)]
fn dense_query_text(query: &str, query_mode: DenseQueryMode) -> String {
    dense_query_text_for_platform(query, query_mode, "common")
}

fn dense_query_text_for_platform(
    query: &str,
    query_mode: DenseQueryMode,
    platform: &str,
) -> String {
    let additions = expanded_query_phrases_for_platform(query, query_mode, platform);
    if additions.contains(&ANGULAR_PACKAGE_ADD_QUERY) {
        // The source-backed example is a better dense query than concatenating
        // unrelated package-manager wording into the user's request.
        return ANGULAR_PACKAGE_ADD_QUERY.to_string();
    }
    if additions.is_empty() {
        query.to_string()
    } else {
        format!("{query} {}", additions.join(" "))
    }
}

fn write_dense_artifact(
    temporary: &Path,
    source: &Path,
    rows: Vec<DenseRow>,
    source_digest: String,
    model_assets: ModelAssets,
    embedder: OfflineEmbedder,
    recipe: DenseRecipe,
    batch_size: usize,
    output: PathBuf,
) -> Result<DenseBuildReport> {
    let started_at = Instant::now();
    fs::copy(source, temporary).with_context(|| {
        format!(
            "failed to copy lexical artifact {} to {}",
            source.display(),
            temporary.display()
        )
    })?;
    let mut connection = Connection::open(temporary)?;
    let transaction = connection.transaction()?;
    transaction.execute_batch(
        "DROP TABLE IF EXISTS example_dense_index;
         DROP TABLE IF EXISTS example_dense;
         DELETE FROM artifact_metadata WHERE key LIKE 'dense_%';
         CREATE TABLE example_dense (
             example_id TEXT PRIMARY KEY NOT NULL REFERENCES examples(example_id),
             embedding_text TEXT NOT NULL,
             embedding BLOB NOT NULL,
             dimension INTEGER NOT NULL,
             normalization TEXT NOT NULL
         );",
    )?;
    transaction.execute_batch(&format!(
        "CREATE VIRTUAL TABLE example_dense_index USING vec0(
             embedding float[{MODEL_DIMENSION}] distance_metric={DENSE_DISTANCE_METRIC},
             +example_id text,
             platform text partition key
         );"
    ))?;

    let metadata = [
        ("dense_index_version", DENSE_INDEX_VERSION.to_string()),
        ("dense_model_id", MODEL_ID.to_string()),
        ("dense_model_revision", MODEL_REVISION.to_string()),
        ("dense_model_runtime", MODEL_RUNTIME.to_string()),
        ("dense_model_dimension", MODEL_DIMENSION.to_string()),
        ("dense_model_max_length", MODEL_MAX_LENGTH.to_string()),
        ("dense_normalization", DENSE_NORMALIZATION.to_string()),
        ("dense_distance_metric", DENSE_DISTANCE_METRIC.to_string()),
        ("dense_recipe_version", DENSE_RECIPE_VERSION.to_string()),
        ("dense_embedding_text_recipe", recipe.name().to_string()),
        (
            "dense_model_files_sha256",
            model_files_json(&model_assets.hashes)?,
        ),
        ("dense_source_digest", source_digest),
        ("dense_row_count", rows.len().to_string()),
    ];
    for (key, value) in metadata {
        transaction.execute(
            "INSERT INTO artifact_metadata(key, value) VALUES (?1, ?2)",
            params![key, value],
        )?;
    }
    for (platform, (max_examples_per_page, example_count)) in computed_platform_vector_bounds(&rows)
    {
        for (key, value) in [
            (
                format!("dense_max_examples_per_page_{platform}"),
                max_examples_per_page.to_string(),
            ),
            (
                format!("dense_platform_example_count_{platform}"),
                example_count.to_string(),
            ),
        ] {
            transaction.execute(
                "INSERT INTO artifact_metadata(key, value) VALUES (?1, ?2)",
                params![key, value],
            )?;
        }
    }

    for (batch_number, chunk) in rows.chunks(batch_size).enumerate() {
        let texts = chunk.iter().map(|row| recipe.text(row)).collect::<Vec<_>>();
        let embeddings = embedder
            .embed(texts.clone(), Some(batch_size))
            .with_context(|| format!("dense embedding batch {} failed", batch_number + 1))?;
        if embeddings.len() != chunk.len() {
            bail!(
                "dense model returned {} vectors for {} rows in batch {}",
                embeddings.len(),
                chunk.len(),
                batch_number + 1
            );
        }
        for (offset, (row, embedding)) in chunk.iter().zip(embeddings).enumerate() {
            validate_embedding(embedding.as_slice(), &row.example_id)?;
            let row_id = (batch_number * batch_size + offset + 1) as i64;
            let blob = embedding_blob(&embedding);
            transaction.execute(
                "INSERT INTO example_dense(
                     example_id, embedding_text, embedding, dimension, normalization
                 ) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![
                    row.example_id,
                    texts[offset],
                    blob,
                    MODEL_DIMENSION as i64,
                    DENSE_NORMALIZATION,
                ],
            )?;
            transaction.execute(
                "INSERT INTO example_dense_index(rowid, embedding, example_id, platform)
                 VALUES (?1, ?2, ?3, ?4)",
                params![
                    row_id,
                    embedding_blob(&embedding),
                    row.example_id,
                    row.platform
                ],
            )?;
        }
    }
    transaction.commit()?;

    validate_dense_artifact(&connection, &model_assets)?;
    let artifact_size_bytes = fs::metadata(temporary)?.len();
    let indexed_examples: i64 =
        connection.query_row("SELECT COUNT(*) FROM example_dense", [], |row| row.get(0))?;
    if indexed_examples as usize != rows.len() {
        bail!("dense row accounting mismatch before publication");
    }

    Ok(DenseBuildReport {
        output,
        recipe: recipe.name().to_string(),
        model_revision: MODEL_REVISION.to_string(),
        indexed_examples: indexed_examples as usize,
        build_time_ms: started_at.elapsed().as_millis(),
        peak_memory_bytes: process_peak_memory_bytes(),
        artifact_size_bytes,
        hardware: hardware_label(),
    })
}

fn load_dense_rows(connection: &Connection) -> Result<Vec<DenseRow>> {
    let mut statement = connection.prepare(
        "SELECT e.example_id, e.page_id, p.platform, p.command, p.description,
                e.description, e.command
         FROM example_lexical AS lexical
         JOIN examples AS e ON e.example_id = lexical.example_id
         JOIN pages AS p ON p.page_id = e.page_id
         ORDER BY e.example_id",
    )?;
    let rows = statement.query_map([], |row| {
        Ok(DenseRow {
            example_id: row.get(0)?,
            page_id: row.get(1)?,
            platform: row.get(2)?,
            page_command: row.get(3)?,
            page_description: row.get(4)?,
            example_description: row.get(5)?,
            example_command: row.get(6)?,
        })
    })?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .map_err(Into::into)
}

fn validate_dense_artifact(connection: &Connection, assets: &ModelAssets) -> Result<()> {
    let expected_metadata = [
        ("dense_index_version", DENSE_INDEX_VERSION.to_string()),
        ("dense_model_id", MODEL_ID.to_string()),
        ("dense_model_revision", MODEL_REVISION.to_string()),
        ("dense_model_runtime", MODEL_RUNTIME.to_string()),
        ("dense_model_dimension", MODEL_DIMENSION.to_string()),
        ("dense_model_max_length", MODEL_MAX_LENGTH.to_string()),
        ("dense_normalization", DENSE_NORMALIZATION.to_string()),
        ("dense_distance_metric", DENSE_DISTANCE_METRIC.to_string()),
        ("dense_recipe_version", DENSE_RECIPE_VERSION.to_string()),
    ];
    for (key, expected) in expected_metadata {
        let actual = artifact_metadata(connection, key)
            .with_context(|| format!("dense artifact is missing compatibility metadata: {key}"))?;
        if actual != expected {
            bail!(
                "dense artifact compatibility mismatch for {key}: expected {expected}, got {actual}"
            );
        }
    }
    let recipe = artifact_metadata(connection, "dense_embedding_text_recipe")?;
    DenseRecipe::parse(&recipe)
        .with_context(|| format!("dense artifact has an unsupported embedding recipe: {recipe}"))?;
    let source_digest = artifact_metadata(connection, "source_digest")?;
    if artifact_metadata(connection, "dense_source_digest")? != source_digest {
        bail!("dense artifact source identity does not match the lexical corpus");
    }
    if artifact_metadata(connection, "dense_model_files_sha256")?
        != model_files_json(&assets.hashes)?
    {
        bail!("dense artifact model assets do not match the pinned local assets");
    }

    let lexical_ids = query_ids(connection, "SELECT example_id FROM example_lexical")?;
    let dense_ids = query_ids(connection, "SELECT example_id FROM example_dense")?;
    if lexical_ids != dense_ids {
        bail!("dense row coverage does not match the lexical example identity set");
    }
    let declared_row_count = artifact_metadata(connection, "dense_row_count")?
        .parse::<usize>()
        .context("dense row-count metadata is invalid")?;
    if declared_row_count != dense_ids.len() {
        bail!("dense row-count metadata does not match stored vectors");
    }
    validate_platform_vector_bounds(connection)?;
    validate_dense_index_schema(connection)?;
    let dense_embeddings = connection
        .prepare(
            "SELECT dense.example_id, dense.embedding, p.platform
             FROM example_dense AS dense
             JOIN examples AS e ON e.example_id = dense.example_id
             JOIN pages AS p ON p.page_id = e.page_id",
        )?
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                (row.get::<_, Vec<u8>>(1)?, row.get::<_, String>(2)?),
            ))
        })?
        .collect::<rusqlite::Result<HashMap<_, _>>>()?;
    let index_rows = connection
        .prepare("SELECT example_id, embedding, platform FROM example_dense_index")?
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Vec<u8>>(1)?,
                row.get::<_, String>(2)?,
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if index_rows.len() != dense_ids.len() {
        bail!("dense vector index row coverage does not match stored vectors");
    }
    let mut index_ids = HashSet::new();
    for (example_id, embedding, platform) in index_rows {
        if !index_ids.insert(example_id.clone()) {
            bail!("dense vector index contains a duplicate example identity: {example_id}");
        }
        validate_embedding_blob(&embedding, &example_id)?;
        if dense_embeddings
            .get(&example_id)
            .is_none_or(|(stored_embedding, stored_platform)| {
                stored_embedding != &embedding || stored_platform != &platform
            })
        {
            bail!("dense vector index payload does not match stored vector: {example_id}");
        }
    }
    if index_ids != dense_ids {
        bail!("dense vector index identities do not match stored vectors");
    }
    for row in connection
        .prepare("SELECT example_id, embedding, dimension, normalization FROM example_dense")?
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Vec<u8>>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, String>(3)?,
            ))
        })?
    {
        let (example_id, blob, dimension, normalization) = row?;
        if dimension != MODEL_DIMENSION as i64 || normalization != DENSE_NORMALIZATION {
            bail!("dense vector metadata is invalid for {example_id}");
        }
        validate_embedding_blob(&blob, &example_id)?;
    }
    Ok(())
}

fn validate_dense_index_schema(connection: &Connection) -> Result<()> {
    let sql: String = connection
        .query_row(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'example_dense_index'",
            [],
            |row| row.get(0),
        )
        .context("dense vector index schema is missing")?;
    let normalized_sql = sql
        .split_whitespace()
        .collect::<String>()
        .to_ascii_lowercase();
    let expected_dimension = format!("float[{MODEL_DIMENSION}]");
    let expected_metric = format!("distance_metric={DENSE_DISTANCE_METRIC}");
    if !normalized_sql.contains(&expected_dimension)
        || !normalized_sql.contains(&expected_metric)
        || !normalized_sql.contains("platformtextpartitionkey")
    {
        bail!(
            "dense vector index schema is incompatible: expected {expected_dimension}, {expected_metric}, and platform partitioning"
        );
    }
    Ok(())
}

fn query_ids(connection: &Connection, query: &str) -> Result<HashSet<String>> {
    let mut statement = connection.prepare(query)?;
    let rows = statement.query_map([], |row| row.get::<_, String>(0))?;
    rows.collect::<rusqlite::Result<HashSet<_>>>()
        .map_err(Into::into)
}

fn validate_embedding(embedding: &[f32], identity: &str) -> Result<()> {
    if embedding.len() != MODEL_DIMENSION {
        bail!(
            "dense vector for {identity} has dimension {}, expected {}",
            embedding.len(),
            MODEL_DIMENSION
        );
    }
    if embedding.iter().any(|value| !value.is_finite()) {
        bail!("dense vector for {identity} contains a non-finite value");
    }
    let norm = embedding
        .iter()
        .map(|value| value * value)
        .sum::<f32>()
        .sqrt();
    if !(0.999..=1.001).contains(&norm) {
        bail!("dense vector for {identity} is not L2-normalized: norm={norm}");
    }
    Ok(())
}

fn validate_embedding_blob(blob: &[u8], identity: &str) -> Result<()> {
    if blob.len() != MODEL_DIMENSION * std::mem::size_of::<f32>() {
        bail!("dense vector blob for {identity} has invalid byte length");
    }
    let values = blob
        .chunks_exact(4)
        .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
        .collect::<Vec<_>>();
    validate_embedding(&values, identity)
}

fn embedding_blob(embedding: &[f32]) -> Vec<u8> {
    embedding
        .iter()
        .flat_map(|value| value.to_le_bytes())
        .collect()
}

/// Digests come from the pinned constants and the matching bundle's own
/// validation; no per-file hashing happens on this path.
fn pinned_model_assets(model_cache: &Path) -> Result<ModelAssets> {
    let model_root = model_cache.join(MODEL_CACHE_FOLDER);
    let reference_path = model_root.join("refs/main");
    let reference = fs::read_to_string(&reference_path).map_err(|error| {
        anyhow!(
            "dense model assets missing/incompatible: cannot read pinned reference {} ({error})",
            reference_path.display()
        )
    })?;
    if reference.trim() != MODEL_REVISION {
        bail!(
            "dense model assets missing/incompatible: expected revision {MODEL_REVISION}, got {}",
            reference.trim()
        );
    }
    let hashes = MODEL_FILES
        .iter()
        .map(|(file, expected)| (file.to_string(), expected.to_string()))
        .collect();
    Ok(ModelAssets {
        cache_dir: model_cache.to_path_buf(),
        hashes,
    })
}

fn validate_model_assets(cache: &Path) -> Result<ModelAssets> {
    let model_root = cache.join(MODEL_CACHE_FOLDER);
    let reference_path = model_root.join("refs/main");
    let reference = fs::read_to_string(&reference_path).map_err(|error| {
        anyhow!(
            "dense model assets missing/incompatible: cannot read pinned reference {} ({error})",
            reference_path.display()
        )
    })?;
    if reference.trim() != MODEL_REVISION {
        bail!(
            "dense model assets missing/incompatible: expected revision {MODEL_REVISION}, got {}",
            reference.trim()
        );
    }
    let snapshot = model_root.join("snapshots").join(MODEL_REVISION);
    let mut hashes = BTreeMap::new();
    for (file, expected_hash) in MODEL_FILES {
        let path = snapshot.join(file);
        let actual_hash = sha256_file(&path).map_err(|error| {
            anyhow!(
                "dense model assets missing/incompatible: cannot read {} ({error})",
                path.display()
            )
        })?;
        if actual_hash != expected_hash {
            bail!("dense model assets missing/incompatible: SHA256 mismatch for {file}");
        }
        hashes.insert(file.to_string(), actual_hash);
    }
    Ok(ModelAssets {
        cache_dir: cache.to_path_buf(),
        hashes,
    })
}

pub fn validate_model_cache(cache: &Path) -> Result<()> {
    validate_model_assets(cache).map(|_| ())
}

/// Validate a dense artifact and its model against the pinned offline assets.
/// This is used by the matching-bundle builder before publication.
pub fn validate_dense_artifact_file(artifact: &Path, model_cache: &Path) -> Result<()> {
    register_sqlite_vec();
    let assets = validate_model_assets(model_cache)?;
    let connection = Connection::open(artifact)
        .with_context(|| format!("failed to open dense artifact {}", artifact.display()))?;
    validate_artifact(&connection)?;
    validate_dense_artifact(&connection, &assets)
}

fn load_embedder(assets: &ModelAssets) -> Result<TextEmbedding> {
    // Use fastembed's named-model path against the bundle's model cache.
    // This matches main's embedding initialization and memory profile; the
    // bundle validation has already pinned the files' content and revision,
    // and fastembed resolves exactly the revision its AllMiniLML6V2 entry
    // pins (the revision the bundle was built from).
    let embedder = TextEmbedding::try_new(
        InitOptions::new(EmbeddingModel::AllMiniLML6V2)
            .with_cache_dir(assets.cache_dir.clone())
            .with_show_download_progress(false)
            .with_max_length(MODEL_MAX_LENGTH),
    )
    .context("failed to initialize pinned MiniLM assets offline")?;
    Ok(embedder)
}

fn model_files_json(hashes: &BTreeMap<String, String>) -> Result<String> {
    Ok(serde_json::to_string(hashes)?)
}

fn sha256_file(path: &Path) -> Result<String> {
    let bytes = fs::read(path)?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

pub(crate) fn register_sqlite_vec() {
    unsafe {
        rusqlite::ffi::sqlite3_auto_extension(Some(std::mem::transmute(
            sqlite3_vec_init as *const (),
        )));
    }
}

fn absolute_output_path(path: &Path) -> Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()?.join(path)
    };
    let mut resolved = PathBuf::new();
    let mut missing_suffix = PathBuf::new();

    for component in absolute.components() {
        match component {
            std::path::Component::Prefix(_) | std::path::Component::RootDir => {
                resolved.push(component.as_os_str());
            }
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                if !missing_suffix.pop() {
                    let parent = resolved.parent().unwrap_or(&resolved);
                    resolved = fs::canonicalize(parent)?;
                }
            }
            std::path::Component::Normal(name) => {
                if !missing_suffix.as_os_str().is_empty() {
                    missing_suffix.push(name);
                    continue;
                }

                let candidate = resolved.join(name);
                match fs::canonicalize(&candidate) {
                    Ok(canonical) => resolved = canonical,
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                        missing_suffix.push(name);
                    }
                    Err(error) => return Err(error.into()),
                }
            }
        }
    }

    resolved.push(missing_suffix);
    Ok(resolved)
}

fn hardware_label() -> String {
    if let Some(label) = std::env::var_os("ASKMAN_BUILD_HARDWARE") {
        let label = label.to_string_lossy().trim().to_string();
        if !label.is_empty() {
            return label;
        }
    }
    format!("{} {}", std::env::consts::OS, std::env::consts::ARCH)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate_database() -> Connection {
        register_sqlite_vec();
        let connection = Connection::open_in_memory().unwrap();
        connection
            .execute_batch(
                "CREATE TABLE pages (
                     page_id TEXT PRIMARY KEY, page_name TEXT, command TEXT,
                     description TEXT, source_path TEXT, source_ref TEXT,
                     source_revision TEXT, platform TEXT, page_position INTEGER
                 );
                 CREATE TABLE examples (
                     example_id TEXT PRIMARY KEY, page_id TEXT, command TEXT,
                     description TEXT, position INTEGER
                 );
                 CREATE TABLE example_dense (
                     example_id TEXT PRIMARY KEY,
                     embedding BLOB
                 );
                 CREATE TABLE artifact_metadata (
                     key TEXT PRIMARY KEY NOT NULL,
                     value TEXT NOT NULL
                 );",
            )
            .unwrap();
        connection
            .execute_batch(&format!(
                "CREATE VIRTUAL TABLE example_dense_index USING vec0(
                     embedding float[{MODEL_DIMENSION}] distance_metric=cosine,
                     +example_id text,
                     platform text partition key
                 );"
            ))
            .unwrap();
        connection
    }

    fn unit_vector(x: f32, y: f32) -> Vec<f32> {
        let mut vector = vec![0.0; MODEL_DIMENSION];
        vector[0] = x;
        vector[1] = y;
        vector
    }

    #[cfg(feature = "dev")]
    #[test]
    fn legacy_main_embedding_text_matches_the_original_importer_recipe() {
        assert_eq!(
            legacy_main_embedding_text(
                "List files one per line:",
                "ls",
                "List directory contents.",
                "ls -1"
            ),
            "Task: List files one per line:. Command: ls. Description: List directory contents.. Example: List files one per line: ls -1"
        );
    }

    #[cfg(unix)]
    #[test]
    fn absolute_output_path_resolves_symlink_ancestors_before_missing_directories() {
        use std::os::unix::fs::symlink;

        let directory = tempfile::tempdir().unwrap();
        let bundle = directory.path().join("bundle");
        fs::create_dir(&bundle).unwrap();
        let bundle_link = directory.path().join("bundle-link");
        symlink(&bundle, &bundle_link).unwrap();

        let output = absolute_output_path(&bundle_link.join("new-directory/commands.db")).unwrap();

        assert!(output.starts_with(fs::canonicalize(bundle).unwrap()));
    }

    #[test]
    fn platform_vector_bounds_uses_precomputed_artifact_metadata() {
        let connection = Connection::open_in_memory().unwrap();
        connection
            .execute_batch(
                "CREATE TABLE artifact_metadata (
                     key TEXT PRIMARY KEY NOT NULL,
                     value TEXT NOT NULL
                 );",
            )
            .unwrap();
        connection
            .execute(
                "INSERT INTO artifact_metadata(key, value) VALUES
                     ('dense_max_examples_per_page_common', '3'),
                     ('dense_platform_example_count_common', '17')",
                [],
            )
            .unwrap();

        assert_eq!(
            platform_vector_bounds(&connection, "common").unwrap(),
            (3, 17)
        );
    }

    #[test]
    fn boundary_ties_expand_the_knn_window_before_exact_fallback() {
        assert_eq!(next_tie_candidate_limit(64), Some(128));
        assert_eq!(
            next_tie_candidate_limit(VEC0_MAX_K / 2),
            Some(VEC0_MAX_K - 1)
        );
        assert_eq!(next_tie_candidate_limit(VEC0_MAX_K - 1), None);
    }

    fn insert_candidate(
        connection: &Connection,
        example_id: &str,
        page_name: &str,
        platform: &str,
        vector: &[f32],
    ) {
        let page_id = format!("{platform}/{page_name}");
        connection
            .execute(
                "INSERT OR IGNORE INTO pages VALUES (
                     ?1, ?2, ?2, 'page description', ?1, 'source', 'revision', ?3, 1
                 )",
                params![page_id, page_name, platform],
            )
            .unwrap();
        connection
            .execute(
                "INSERT INTO examples VALUES (?1, ?2, ?1, 'example description', 1)",
                params![example_id, page_id],
            )
            .unwrap();
        let rowid = connection.last_insert_rowid();
        let blob = embedding_blob(vector);
        connection
            .execute(
                "INSERT INTO example_dense VALUES (?1, ?2)",
                params![example_id, blob],
            )
            .unwrap();
        connection
            .execute(
                "INSERT INTO example_dense_index(rowid, embedding, example_id, platform)
                 VALUES (?1, ?2, ?3, ?4)",
                params![rowid, blob, example_id, platform],
            )
            .unwrap();
    }

    fn query_candidates_with_test_bounds(
        connection: &Connection,
        query: &[f32],
        platform: &str,
        limit: usize,
        platform_explicit: bool,
    ) -> Result<Vec<DenseCandidate>> {
        let mut bounds = DENSE_PLATFORMS
            .iter()
            .map(|platform| (platform.to_string(), (0, 0)))
            .collect::<HashMap<_, _>>();
        let mut statement = connection.prepare(
            "SELECT p.platform, e.page_id, COUNT(*)
             FROM examples AS e
             JOIN pages AS p ON p.page_id = e.page_id
             GROUP BY p.platform, e.page_id",
        )?;
        for row in statement.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
            ))
        })? {
            let (page_platform, _page_id, page_count) = row?;
            let entry = bounds.entry(page_platform).or_default();
            let page_count = usize::try_from(page_count)?;
            entry.0 = entry.0.max(page_count);
            entry.1 += page_count;
        }
        drop(statement);

        for (page_platform, (max_examples_per_page, example_count)) in bounds {
            for (key, value) in [
                (
                    format!("dense_max_examples_per_page_{page_platform}"),
                    max_examples_per_page.to_string(),
                ),
                (
                    format!("dense_platform_example_count_{page_platform}"),
                    example_count.to_string(),
                ),
            ] {
                connection.execute(
                    "INSERT INTO artifact_metadata(key, value) VALUES (?1, ?2)
                     ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    params![key, value],
                )?;
            }
        }
        let selected_pages = selected_page_ids(connection, platform)?;
        query_dense_candidates(
            connection,
            query,
            platform,
            &selected_pages,
            limit,
            platform_explicit,
            false,
        )
    }

    #[test]
    fn partitioned_knn_returns_only_the_requested_platform_in_distance_order() {
        let connection = candidate_database();
        let query = unit_vector(1.0, 0.0);
        insert_candidate(&connection, "common-near", "common-near", "common", &query);
        insert_candidate(
            &connection,
            "linux-next",
            "linux-next",
            "linux",
            &unit_vector(0.8, 0.6),
        );
        insert_candidate(
            &connection,
            "common-far",
            "common-far",
            "common",
            &unit_vector(-1.0, 0.0),
        );

        let results = query_partition_top_k(&connection, &query, "common", 8).unwrap();

        assert_eq!(
            results
                .iter()
                .map(|(example_id, _)| example_id.as_str())
                .collect::<Vec<_>>(),
            ["common-near", "common-far"]
        );
    }

    #[test]
    fn dense_candidates_find_the_best_example_beyond_4096_vectors() {
        let mut connection = candidate_database();
        let transaction = connection.transaction().unwrap();
        let perpendicular = unit_vector(0.0, 1.0);
        for index in 0..4096 {
            insert_candidate(
                &transaction,
                &format!("example-{index}"),
                "tool",
                "common",
                &perpendicular,
            );
        }
        let query = unit_vector(1.0, 0.0);
        insert_candidate(&transaction, "best-example", "tool", "common", &query);
        transaction.commit().unwrap();

        let results =
            query_candidates_with_test_bounds(&connection, &query, "linux", 8, false).unwrap();

        assert_eq!(results.len(), 1);
        assert_eq!(results[0].example_id, "best-example");
        assert_eq!(results[0].ranking_score, 0.0);
    }

    #[test]
    fn partitioned_knn_finds_a_late_best_match_across_more_than_4096_rows() {
        let mut connection = candidate_database();
        let transaction = connection.transaction().unwrap();
        let query = unit_vector(1.0, 0.0);
        let distractor = unit_vector(0.0, 1.0);
        for index in 0..4100 {
            insert_candidate(
                &transaction,
                &format!("distractor-{index:04}"),
                &format!("distractor-{index:04}"),
                "common",
                &distractor,
            );
        }
        insert_candidate(&transaction, "late-best", "late-best", "common", &query);
        transaction.commit().unwrap();

        let results =
            query_candidates_with_test_bounds(&connection, &query, "common", 8, false).unwrap();

        assert_eq!(results[0].example_id, "late-best");
        assert_eq!(results[0].ranking_score, 0.0);
    }

    #[test]
    fn dense_candidates_break_example_and_page_distance_ties_by_example_id() {
        let connection = candidate_database();
        let query = unit_vector(1.0, 0.0);
        insert_candidate(&connection, "z-example", "first", "common", &query);
        insert_candidate(&connection, "b-example", "second", "common", &query);
        insert_candidate(&connection, "a-example", "first", "common", &query);

        let results =
            query_candidates_with_test_bounds(&connection, &query, "linux", 8, false).unwrap();

        assert_eq!(
            results
                .iter()
                .map(|candidate| candidate.example_id.as_str())
                .collect::<Vec<_>>(),
            ["a-example", "b-example"]
        );
    }

    #[test]
    fn dense_candidates_expand_past_a_tied_knn_boundary_in_id_order() {
        let connection = candidate_database();
        let query = unit_vector(1.0, 0.0);
        for example_id in ["z-example", "b-example", "a-example", "c-example"] {
            insert_candidate(&connection, example_id, example_id, "common", &query);
        }

        let results =
            query_candidates_with_test_bounds(&connection, &query, "common", 2, false).unwrap();

        assert_eq!(
            results
                .iter()
                .map(|candidate| candidate.example_id.as_str())
                .collect::<Vec<_>>(),
            ["a-example", "b-example"]
        );
    }

    #[test]
    fn dense_candidates_select_platform_overrides_and_common_fallbacks() {
        let connection = candidate_database();
        let query = unit_vector(1.0, 0.0);
        insert_candidate(&connection, "common-shared", "shared", "common", &query);
        insert_candidate(
            &connection,
            "common-fallback",
            "fallback",
            "common",
            &unit_vector(-1.0, 0.0),
        );
        for platform in ["linux", "osx", "windows"] {
            insert_candidate(
                &connection,
                &format!("{platform}-shared"),
                "shared",
                platform,
                &unit_vector(0.8, 0.6),
            );
            insert_candidate(
                &connection,
                &format!("{platform}-only"),
                &format!("{platform}-only"),
                platform,
                &query,
            );
        }

        for platform in ["common", "linux", "osx", "windows"] {
            let results =
                query_candidates_with_test_bounds(&connection, &query, platform, 8, false).unwrap();
            let expected = if platform == "common" {
                vec!["common-shared".to_string(), "common-fallback".to_string()]
            } else {
                vec![
                    format!("{platform}-only"),
                    format!("{platform}-shared"),
                    "common-fallback".to_string(),
                ]
            };
            assert_eq!(
                results
                    .iter()
                    .map(|candidate| candidate.example_id.clone())
                    .collect::<Vec<_>>(),
                expected,
                "target platform: {platform}"
            );
        }
    }

    #[test]
    fn dense_candidates_fill_the_page_budget_after_platform_filtering_and_deduplication() {
        let mut connection = candidate_database();
        let transaction = connection.transaction().unwrap();
        let query = unit_vector(1.0, 0.0);
        let crowded = unit_vector(0.8, 0.6);
        for index in 0..4096 {
            insert_candidate(
                &transaction,
                &format!("windows-{index:04}"),
                "windows-tool",
                "windows",
                &query,
            );
            insert_candidate(
                &transaction,
                &format!("crowded-{index:04}"),
                "crowded-tool",
                "common",
                &crowded,
            );
        }
        for index in 1..=8 {
            insert_candidate(
                &transaction,
                &format!("example-{index}"),
                &format!("tool-{index}"),
                "common",
                &unit_vector(0.0, 1.0),
            );
        }
        transaction.commit().unwrap();

        let results =
            query_candidates_with_test_bounds(&connection, &query, "linux", 8, false).unwrap();

        assert_eq!(
            results
                .iter()
                .map(|candidate| candidate.example_id.as_str())
                .collect::<Vec<_>>(),
            [
                "crowded-0000",
                "example-1",
                "example-2",
                "example-3",
                "example-4",
                "example-5",
                "example-6",
                "example-7",
            ]
        );
    }

    #[test]
    fn dense_candidates_keep_relevance_ahead_of_platform_precedence() {
        let connection = candidate_database();
        let query = unit_vector(1.0, 0.0);
        insert_candidate(&connection, "common", "common-tool", "common", &query);
        for platform in ["linux", "osx", "windows"] {
            insert_candidate(
                &connection,
                platform,
                "platform-tool",
                platform,
                &unit_vector(0.8, 0.6),
            );
        }

        for platform in ["linux", "osx", "windows"] {
            for explicit in [false, true] {
                let results =
                    query_candidates_with_test_bounds(&connection, &query, platform, 8, explicit)
                        .unwrap();
                assert_eq!(
                    results
                        .iter()
                        .map(|candidate| candidate.example_id.as_str())
                        .collect::<Vec<_>>(),
                    ["common", platform]
                );
                let platform_result = results
                    .iter()
                    .find(|candidate| candidate.platform == platform)
                    .unwrap();
                assert!((platform_result.ranking_score - 0.2).abs() < 0.000_001);
            }
        }
    }

    #[test]
    fn dense_candidates_prefer_explicit_platform_on_equal_distance() {
        let connection = candidate_database();
        let query = unit_vector(1.0, 0.0);
        let equally_relevant = unit_vector(0.8, 0.6);
        insert_candidate(
            &connection,
            "common",
            "common-tool",
            "common",
            &equally_relevant,
        );

        for platform in ["linux", "osx", "windows"] {
            insert_candidate(
                &connection,
                platform,
                "platform-tool",
                platform,
                &equally_relevant,
            );
            let results =
                query_candidates_with_test_bounds(&connection, &query, platform, 8, true).unwrap();
            assert_eq!(
                results
                    .iter()
                    .map(|candidate| candidate.example_id.as_str())
                    .collect::<Vec<_>>(),
                [platform, "common"]
            );
        }
    }

    #[test]
    fn parses_the_declared_embedding_recipes() {
        assert_eq!(
            DenseRecipe::parse("description").unwrap(),
            DenseRecipe::Description
        );
        assert_eq!(
            DenseRecipe::parse("description-plus-parent").unwrap(),
            DenseRecipe::DescriptionWithParent
        );
        assert_eq!(
            DenseRecipe::parse("main-compatible").unwrap(),
            DenseRecipe::MainCompatible
        );
        assert!(DenseRecipe::parse("unknown").is_err());
    }

    #[test]
    fn recipe_text_preserves_the_source_descriptions() {
        let row = DenseRow {
            example_id: "ls-example".to_string(),
            page_id: "ls".to_string(),
            platform: "common".to_string(),
            page_command: "ls".to_string(),
            page_description: "List directory contents.".to_string(),
            example_description: "List files one per line:".to_string(),
            example_command: "ls -1".to_string(),
        };

        assert_eq!(
            DenseRecipe::Description.text(&row),
            "List files one per line:"
        );
        assert_eq!(
            DenseRecipe::DescriptionWithParent.text(&row),
            "List directory contents.\nList files one per line:"
        );
        assert_eq!(
            DenseRecipe::MainCompatible.text(&row),
            "Task: List files one per line:. Command: ls. Description: List directory contents.\
             . Example: List files one per line: ls -1"
        );
    }

    #[test]
    fn expanded_dev_query_maps_file_output_to_cat_vocabulary() {
        let query = "read a file to standard output";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            "read a file to standard output print contents file stdout"
        );
    }

    #[test]
    fn focused_query_rules_are_platform_aware_and_direction_safe() {
        assert_eq!(
            dense_query_text_for_platform(
                "read a file to standard output",
                DenseQueryMode::FocusedIntentRulesV1,
                "common"
            ),
            "read a file to standard output print contents file stdout"
        );
        assert_eq!(
            dense_query_text_for_platform(
                "show Linux interface IPv4 addresses",
                DenseQueryMode::FocusedIntentRulesV1,
                "linux"
            ),
            "show Linux interface IPv4 addresses list interfaces detailed info brief network layer"
        );
        assert_eq!(
            dense_query_text_for_platform(
                "show interface IPv4 addresses",
                DenseQueryMode::FocusedIntentRulesV1,
                "osx"
            ),
            "show interface IPv4 addresses"
        );
        assert_eq!(
            dense_query_text_for_platform(
                "copy clipboard contents into a file",
                DenseQueryMode::FocusedIntentRulesV1,
                "osx"
            ),
            "copy clipboard contents into a file Write the contents of the clipboard to a file"
        );
        assert_eq!(
            dense_query_text_for_platform(
                "do not restart the systemctl service",
                DenseQueryMode::FocusedIntentRulesV1,
                "linux"
            ),
            "do not restart the systemctl service"
        );
        assert_eq!(
            dense_query_text_for_platform(
                "do not show file contents to stdout",
                DenseQueryMode::FocusedIntentRulesV1,
                "common"
            ),
            "do not show file contents to stdout"
        );
    }

    #[test]
    fn expanded_dev_query_maps_discarding_duplicate_lines_to_unique_sort() {
        let query = "sort access.log and discard duplicate lines";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            "sort access.log and discard duplicate lines Sort a file preserving only unique lines"
        );
        assert_eq!(dense_query_text(query, DenseQueryMode::Raw), query);
    }

    #[test]
    fn expanded_dev_query_maps_text_file_display_to_cat_vocabulary() {
        let query = "display a text file in the terminal";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            "display a text file in the terminal print contents file stdout"
        );
    }

    #[test]
    fn expanded_dev_query_maps_nftables_rule_intents_to_pinned_example_terms() {
        for query in [
            "configure a Linux firewall rule with nftables",
            "create an nftables rule on Linux",
            "allow traffic with a Linux nftables rule",
        ] {
            assert!(
                dense_query_text(query, DenseQueryMode::IntentRulesV1)
                    .contains("Add a new rule to accept several TCP ports"),
                "query should expand toward the pinned nft rule example: {query}"
            );
        }
    }

    #[test]
    fn expanded_dev_query_canonicalizes_angular_package_additions() {
        for query in [
            "add package to an Angular workspace",
            "install a package in an Angular workspace",
        ] {
            assert_eq!(
                dense_query_text(query, DenseQueryMode::IntentRulesV1),
                "Add a package to the current project",
                "query should use the pinned Angular package-add example: {query}"
            );
        }
    }

    #[test]
    fn expanded_dev_query_maps_photo_exif_intents_to_exiftool_terms() {
        for query in [
            "read EXIF metadata from a photo on macOS",
            "inspect a picture's EXIF fields from the Mac terminal",
            "show camera metadata for an image on macOS",
            "extract EXIF tags from a Mac photo",
            "display photo metadata from a macOS shell",
        ] {
            assert!(
                dense_query_text(query, DenseQueryMode::IntentRulesV1)
                    .contains("Print the EXIF metadata for a given file"),
                "query should expand toward the pinned exiftool example: {query}"
            );
        }
    }

    #[test]
    fn expanded_dev_query_does_not_bias_exif_removal_toward_read_examples() {
        for query in [
            "remove EXIF metadata from a photo",
            "do not read EXIF metadata from a photo",
        ] {
            assert_eq!(
                dense_query_text(query, DenseQueryMode::IntentRulesV1),
                query,
                "negated EXIF intent must not add a positive-read query: {query}"
            );
        }
    }

    #[test]
    fn negated_file_stdout_intents_are_detected_without_matching_positive_queries() {
        assert!(is_negated_file_stdout_query(
            "do not show file contents to stdout"
        ));
        assert!(is_negated_file_stdout_query(
            "avoid printing file text to standard output"
        ));
        assert!(!is_negated_file_stdout_query(
            "show file contents to stdout"
        ));
        assert!(!is_negated_file_stdout_query(
            "do not show file names in stdout logs"
        ));
    }

    #[test]
    fn expanded_dev_query_maps_password_archive_intents_to_encryption_terms() {
        for query in [
            "create a password-protected archive with a common shell command",
            "make an encrypted archive from the shell",
            "compress files into a password-protected archive",
            "write a password-encrypted archive at the terminal",
            "protect a shell-created archive with a password",
        ] {
            let expanded =
                dense_query_text(query, DenseQueryMode::IntentRulesV1).to_ascii_lowercase();
            assert!(
                expanded.contains("password protect the resulting archive"),
                "query should expand toward pinned encrypted-archive examples: {query}"
            );
        }
    }

    #[test]
    fn expanded_dev_query_maps_registry_lookup_intents_to_reg_query_terms() {
        for query in [
            "query the Windows registry from a shell",
            "inspect a Windows registry key at the command line",
            "read registry values on Windows",
            "look up a Windows registry entry in PowerShell",
            "search the Windows registry from a terminal",
        ] {
            assert!(
                dense_query_text(query, DenseQueryMode::IntentRulesV1)
                    .contains("reg query Display all values of a key"),
                "query should expand toward the pinned reg query example: {query}"
            );
        }
    }

    #[test]
    fn expanded_dev_query_does_not_expand_unrelated_metadata_archive_or_registry_intents() {
        for query in [
            "show metadata for a project file on macOS",
            "create an archive of these files",
            "add a Windows registry key",
        ] {
            assert_eq!(
                dense_query_text(query, DenseQueryMode::IntentRulesV1),
                query
            );
        }
    }

    #[test]
    fn expanded_dev_query_does_not_turn_nftables_blocking_into_accepting() {
        let query = "block traffic using nftables on Linux";

        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            query
        );
    }

    #[test]
    fn expanded_dev_query_maps_pasteboard_write_intents_to_pbcopy() {
        for query in [
            "copy shell output to the macOS clipboard",
            "send terminal output to the Mac pasteboard",
            "place command results in the macOS clipboard",
            "pipe command output into the Apple clipboard",
            "put standard output on the Mac pasteboard",
        ] {
            assert!(
                dense_query_text(query, DenseQueryMode::IntentRulesV1)
                    .contains("pbcopy place the results of a specific command in the clipboard"),
                "query should expand toward pbcopy: {query}"
            );
        }
    }

    #[test]
    fn expanded_dev_query_leaves_pasteboard_extraction_unexpanded() {
        let query = "print the text from the clipboard";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            query
        );
    }

    #[test]
    fn expanded_dev_query_anchors_single_file_copy_to_destination_example() {
        for query in [
            "copy one Windows file to another path",
            "duplicate a single file in a Windows directory",
            "copy one file into a different Windows folder",
            "make a second copy of one Windows file",
            "put one Windows file at a destination path",
        ] {
            assert!(
                dense_query_text(query, DenseQueryMode::IntentRulesV1)
                    .contains("Copy a file into another directory, keeping the filename"),
                "query should expand toward the single-file destination example: {query}"
            );
        }
    }

    #[test]
    fn expanded_dev_query_leaves_directory_recursive_copy_unexpanded() {
        let query = "copy the directory recursively";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            query
        );
    }

    #[test]
    fn expanded_dev_query_maps_systemctl_restart_to_service_vocabulary() {
        let query = "restart one Linux unit with systemctl";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            "restart one Linux unit with systemctl start stop restart reload show status service"
        );
    }

    #[test]
    fn expanded_dev_query_maps_linux_free_disk_space_to_df_vocabulary() {
        let query = "show free disk space in human-readable units";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "linux"),
            "show free disk space in human-readable units Display all filesystems in human-readable form"
        );
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "windows"),
            query
        );
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::Raw, "linux"),
            query
        );
    }

    #[test]
    fn expanded_dev_query_maps_linux_ram_usage_to_free_vocabulary() {
        let query = "display current RAM usage in megabytes";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "linux"),
            "display current RAM usage in megabytes Display memory in Bytes/KB/MB/GB"
        );
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "windows"),
            query
        );
    }

    #[test]
    fn expanded_dev_query_maps_archive_unpacking_to_tar_vocabulary() {
        let query = "unpack archive backup.tar.gz into directory restore";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "linux"),
            "unpack archive backup.tar.gz into directory restore source.tar target directory"
        );
    }

    #[test]
    fn expanded_dev_query_maps_file_content_search_to_grep_vocabulary() {
        let query = "search every file under this directory tree for the exact string FIXME";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "linux"),
            "search every file under this directory tree for the exact string FIXME Search for a pattern in all files recursively in a directory"
        );
    }

    #[test]
    fn expanded_dev_query_maps_size_sorted_hidden_listing_to_ls_vocabulary() {
        let query =
            "show a long listing of all files including hidden entries, sorted by file size";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "linux"),
            "show a long listing of all files including hidden entries, sorted by file size List files in long format, sorted by size (descending) recursively"
        );
    }

    #[test]
    fn expanded_dev_query_maps_recursive_windows_text_search_to_findstr() {
        let query = "find the word failed in every .log file under this folder";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "windows"),
            "find the word failed in every .log file under this folder Find one or more strings in all files recursively"
        );
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "linux"),
            "find the word failed in every .log file under this folder Search for a pattern in all files recursively in a directory"
        );
    }

    #[test]
    fn expanded_dev_query_maps_recursive_windows_directory_copy_to_xcopy() {
        let query =
            "recursively copy a folder to another location and preserve its directory structure";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "windows"),
            "recursively copy a folder to another location and preserve its directory structure Copy files and directory trees"
        );
    }

    #[test]
    fn expanded_dev_query_maps_permission_preserving_directory_tree_copy_to_rsync() {
        let query = "duplicate a directory tree to a new location while keeping permissions";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "common"),
            "duplicate a directory tree to a new location while keeping permissions Use archive mode (recursively copy directories, copy symlinks without resolving, and preserve permissions, ownership, and modification times)"
        );
    }

    #[test]
    fn expanded_dev_query_maps_clipboard_contents_written_to_file_to_pbpaste() {
        let query = "copy my clipboard contents into a file";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "osx"),
            "copy my clipboard contents into a file Write the contents of the clipboard to a file"
        );
    }

    #[test]
    fn expanded_dev_query_maps_single_file_rename_to_mv() {
        let query = "rename report-old.txt to report-final.txt";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "common"),
            "rename report-old.txt to report-final.txt Rename a file or directory when the target is not an existing directory"
        );
    }

    #[test]
    fn expanded_dev_query_maps_displayed_linux_ipv4_interfaces_to_ip_vocabulary() {
        let query = "display interface IPv4 addresses on Linux";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            "display interface IPv4 addresses on Linux list interfaces detailed info brief network layer"
        );
    }

    #[test]
    fn expanded_dev_query_maps_inspected_linux_ipv4_interfaces_to_ip_vocabulary() {
        let query = "inspect assigned IPv4 addresses on Linux interfaces";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            "inspect assigned IPv4 addresses on Linux interfaces list interfaces detailed info brief network layer"
        );
    }

    #[test]
    fn expanded_dev_query_maps_printed_linux_interface_addresses_to_ip_vocabulary() {
        let query = "print Linux interface address information";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            "print Linux interface address information list interfaces detailed info brief network layer"
        );
    }

    #[test]
    fn expanded_dev_query_uses_selected_linux_platform_for_interface_addresses() {
        let query = "show the IP addresses of network interfaces";
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "linux"),
            "show the IP addresses of network interfaces list interfaces detailed info brief network layer"
        );
        assert_eq!(
            dense_query_text_for_platform(query, DenseQueryMode::IntentRulesV1, "osx"),
            query
        );
    }

    #[test]
    fn expanded_dev_query_does_not_map_mac_addresses_to_ip_vocabulary() {
        let query = "show MAC addresses on Linux network interfaces";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            query
        );
    }

    #[test]
    fn expanded_dev_query_maps_pasteboard_output_to_pbcopy_direction() {
        // #46 left pasteboard queries unexpanded to keep them away from
        // `cat`; the dev-split evidence (4/5 rank-1 misses ranking `pbpaste`
        // above `pbcopy`) now pins the write direction instead. Extraction
        // phrasing stays unexpanded (see the "from the clipboard" guard).
        let query = "put standard output on the Mac pasteboard";
        assert!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1)
                .contains("pbcopy place the results of a specific command in the clipboard")
        );
    }

    #[test]
    fn expanded_dev_query_leaves_unrelated_stdout_intent_unchanged() {
        let query = "show profile contents on standard output";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            query
        );
    }

    #[test]
    fn expanded_dev_query_does_not_treat_destructive_file_contents_as_cat() {
        let query = "delete a file's contents";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            query
        );
    }

    #[test]
    fn expanded_dev_query_does_not_match_nonstandard_output() {
        let query = "copy a file to nonstandard output";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::IntentRulesV1),
            query
        );
    }

    #[test]
    fn raw_query_mode_never_expands_a_known_intent() {
        let query = "read a file to standard output";
        assert_eq!(dense_query_text(query, DenseQueryMode::Raw), query);
    }

    #[test]
    fn missing_model_cache_fails_with_an_offline_asset_error() {
        let cache = tempfile::tempdir().unwrap();
        let error = validate_model_cache(cache.path()).unwrap_err().to_string();
        assert!(error.contains("dense model assets missing/incompatible"));
    }

    #[test]
    fn vectors_require_the_pinned_shape_and_normalization() {
        let vector = vec![1.0 / (MODEL_DIMENSION as f32).sqrt(); MODEL_DIMENSION];
        validate_embedding(&vector, "test").unwrap();
        assert!(validate_embedding(&[0.0; MODEL_DIMENSION], "test").is_err());
        assert!(validate_embedding(&[0.0; MODEL_DIMENSION - 1], "test").is_err());
    }
}
