use crate::tldr_subset::{
    artifact_metadata, process_peak_memory_bytes, selected_page_ids, validate_artifact,
};
use anyhow::{Context, Result, anyhow, bail};
use fastembed::{
    InitOptionsUserDefined, Pooling, QuantizationMode, TextEmbedding, TokenizerFiles,
    UserDefinedEmbeddingModel,
};
use rusqlite::{Connection, params};
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
pub const DENSE_INDEX_VERSION: &str = "dense-vec0-v1";
pub const DENSE_NORMALIZATION: &str = "l2";
pub const DENSE_DISTANCE_METRIC: &str = "cosine";
pub const DENSE_RECIPE_VERSION: &str = "dense-text-v1";
pub const DEFAULT_BATCH_SIZE: usize = 32;
const DENSE_QUERY_MODE_ENV: &str = "ASKMAN_DENSE_QUERY_MODE";
const EXPANDED_DEV_QUERY_MODE: &str = "expanded-dev";

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
}

impl DenseRecipe {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "description" => Ok(Self::Description),
            "description-plus-parent" => Ok(Self::DescriptionWithParent),
            _ => bail!(
                "unsupported dense recipe `{value}`; expected description or description-plus-parent"
            ),
        }
    }

    fn name(self) -> &'static str {
        match self {
            Self::Description => "description",
            Self::DescriptionWithParent => "description-plus-parent",
        }
    }

    fn text(self, page_description: &str, example_description: &str) -> String {
        match self {
            Self::Description => example_description.to_string(),
            Self::DescriptionWithParent => {
                format!("{page_description}\n{example_description}")
            }
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
    page_description: String,
    example_description: String,
}

#[derive(Debug)]
struct ModelAssets {
    snapshot: PathBuf,
    hashes: BTreeMap<String, String>,
}

pub(crate) struct DenseIndex {
    connection: Connection,
    embedder: OfflineEmbedder,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum DenseQueryMode {
    Raw,
    ExpandedDev,
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

    /// Open a dense index whose model assets were already verified by the
    /// matching-bundle validation. Digests come from the pinned constants and
    /// no per-file hashing happens on this path.
    pub(crate) fn open_from_bundle(artifact: &Path, model_cache: &Path) -> Result<Self> {
        register_sqlite_vec();
        let assets = pinned_model_assets(model_cache)?;
        Self::open_index(artifact, assets)
    }

    fn open_index(artifact: &Path, assets: ModelAssets) -> Result<Self> {
        let connection = Connection::open(artifact)
            .with_context(|| format!("failed to open dense artifact {}", artifact.display()))?;
        validate_artifact(&connection)?;
        validate_dense_artifact(&connection, &assets)?;
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
    ) -> Result<Vec<DenseCandidate>> {
        if limit == 0 {
            bail!("dense query limit must be greater than zero");
        }
        let dense_query = dense_query_text(query, query_mode);
        let query_vector = self
            .embedder
            .embed(vec![dense_query], Some(1))?
            .pop()
            .ok_or_else(|| anyhow!("dense model returned no query vector"))?;
        validate_embedding(&query_vector, "query")?;

        let selected = selected_page_ids(&self.connection, platform)?
            .into_iter()
            .collect::<HashSet<_>>();
        if selected.is_empty() {
            return Ok(Vec::new());
        }
        let total_vectors: i64 =
            self.connection
                .query_row("SELECT COUNT(*) FROM example_dense_index", [], |row| {
                    row.get(0)
                })?;
        if total_vectors == 0 {
            return Ok(Vec::new());
        }

        let query_blob = embedding_blob(&query_vector);
        let mut statement = self.connection.prepare(
            "SELECT dense.example_id, dense.distance
             FROM example_dense_index AS dense
             WHERE dense.embedding MATCH ?1
             ORDER BY dense.distance
             LIMIT ?2",
        )?;
        let mut details = self.connection.prepare(
            "SELECT e.example_id, e.page_id, p.command, e.command, p.description, e.description,
                    p.source_path, p.source_ref, p.source_revision, p.platform,
                    p.page_position, e.position
             FROM examples AS e
             JOIN pages AS p ON p.page_id = e.page_id
             WHERE e.example_id = ?1",
        )?;
        let rows = statement.query_map(params![query_blob, total_vectors], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, f64>(1)?))
        })?;

        let mut seen_pages = HashSet::new();
        let mut results = Vec::new();
        for row in rows {
            let (example_id, distance) = row?;
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
            if !selected.contains(&candidate.page_id)
                || !seen_pages.insert(candidate.page_id.clone())
            {
                continue;
            }
            results.push(candidate);
            if results.len() == limit {
                break;
            }
        }
        Ok(results)
    }
}

fn dense_server_query_mode() -> Result<DenseQueryMode> {
    match std::env::var(DENSE_QUERY_MODE_ENV) {
        Ok(value) if value == EXPANDED_DEV_QUERY_MODE => Ok(DenseQueryMode::ExpandedDev),
        Ok(value) => bail!(
            "unsupported {DENSE_QUERY_MODE_ENV} value `{value}`; unset it for raw queries or use `{EXPANDED_DEV_QUERY_MODE}`"
        ),
        Err(std::env::VarError::NotPresent) => Ok(DenseQueryMode::Raw),
        Err(std::env::VarError::NotUnicode(_)) => {
            bail!("{DENSE_QUERY_MODE_ENV} must contain valid Unicode")
        }
    }
}

fn dense_query_text(query: &str, query_mode: DenseQueryMode) -> String {
    if query_mode == DenseQueryMode::Raw {
        return query.to_string();
    }

    let normalized = query.to_ascii_lowercase();
    let query_words = normalized
        .split(|character: char| !character.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .collect::<Vec<_>>();
    let mut additions = Vec::new();

    let mentions_file = query_words.contains(&"file");
    let mentions_standard_output = query_words
        .windows(2)
        .any(|words| words == ["standard", "output"]);
    let names_file_contents = query_words.contains(&"contents");
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

    let names_linux_ipv4_interfaces = query_words.contains(&"linux")
        && query_words.contains(&"ipv4")
        && (query_words.contains(&"interface") || query_words.contains(&"interfaces"));
    let requests_interface_observation = ["display", "inspect", "show", "list"]
        .iter()
        .any(|term| query_words.contains(term));
    if names_linux_ipv4_interfaces && requests_interface_observation {
        // These terms occur in the pinned observation descriptions. `address`
        // also occurs in add/delete descriptions, so it would broaden the intent.
        additions.push("list interfaces detailed info brief network layer");
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
             +example_id text
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

    for (batch_number, chunk) in rows.chunks(batch_size).enumerate() {
        let texts = chunk
            .iter()
            .map(|row| recipe.text(&row.page_description, &row.example_description))
            .collect::<Vec<_>>();
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
                "INSERT INTO example_dense_index(rowid, embedding, example_id)
                 VALUES (?1, ?2, ?3)",
                params![row_id, embedding_blob(&embedding), row.example_id],
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
        "SELECT e.example_id, p.description, e.description
         FROM example_lexical AS lexical
         JOIN examples AS e ON e.example_id = lexical.example_id
         JOIN pages AS p ON p.page_id = e.page_id
         ORDER BY e.example_id",
    )?;
    let rows = statement.query_map([], |row| {
        Ok(DenseRow {
            example_id: row.get(0)?,
            page_description: row.get(1)?,
            example_description: row.get(2)?,
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
    validate_dense_index_schema(connection)?;
    let dense_embeddings = connection
        .prepare("SELECT example_id, embedding FROM example_dense")?
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
        })?
        .collect::<rusqlite::Result<HashMap<_, _>>>()?;
    let index_rows = connection
        .prepare("SELECT example_id, embedding FROM example_dense_index")?
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if index_rows.len() != dense_ids.len() {
        bail!("dense vector index row coverage does not match stored vectors");
    }
    let mut index_ids = HashSet::new();
    for (example_id, embedding) in index_rows {
        if !index_ids.insert(example_id.clone()) {
            bail!("dense vector index contains a duplicate example identity: {example_id}");
        }
        validate_embedding_blob(&embedding, &example_id)?;
        if dense_embeddings.get(&example_id) != Some(&embedding) {
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
    if !normalized_sql.contains(&expected_dimension) || !normalized_sql.contains(&expected_metric) {
        bail!(
            "dense vector index schema is incompatible: expected {expected_dimension} and {expected_metric}"
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
    let snapshot = model_root.join("snapshots").join(MODEL_REVISION);
    let hashes = MODEL_FILES
        .iter()
        .map(|(file, expected)| (file.to_string(), expected.to_string()))
        .collect();
    Ok(ModelAssets { snapshot, hashes })
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
    Ok(ModelAssets { snapshot, hashes })
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
    let model = UserDefinedEmbeddingModel::new(
        fs::read(assets.snapshot.join("model.onnx"))?,
        TokenizerFiles {
            tokenizer_file: fs::read(assets.snapshot.join("tokenizer.json"))?,
            config_file: fs::read(assets.snapshot.join("config.json"))?,
            special_tokens_map_file: fs::read(assets.snapshot.join("special_tokens_map.json"))?,
            tokenizer_config_file: fs::read(assets.snapshot.join("tokenizer_config.json"))?,
        },
    )
    .with_pooling(Pooling::Mean)
    .with_quantization(QuantizationMode::None);
    TextEmbedding::try_new_from_user_defined(
        model,
        InitOptionsUserDefined::new().with_max_length(MODEL_MAX_LENGTH),
    )
    .context("failed to initialize pinned MiniLM assets offline")
}

fn model_files_json(hashes: &BTreeMap<String, String>) -> Result<String> {
    Ok(serde_json::to_string(hashes)?)
}

fn sha256_file(path: &Path) -> Result<String> {
    let bytes = fs::read(path)?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

fn register_sqlite_vec() {
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
    let normalized = if absolute.exists() {
        fs::canonicalize(&absolute)?
    } else if let Some(parent) = absolute.parent() {
        if parent.exists() {
            fs::canonicalize(parent)?.join(
                absolute
                    .file_name()
                    .ok_or_else(|| anyhow!("output path has no file name"))?,
            )
        } else {
            absolute
        }
    } else {
        absolute
    };
    Ok(normalized)
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
        assert!(DenseRecipe::parse("unknown").is_err());
    }

    #[test]
    fn recipe_text_preserves_the_source_descriptions() {
        assert_eq!(
            DenseRecipe::Description.text("parent", "example"),
            "example"
        );
        assert_eq!(
            DenseRecipe::DescriptionWithParent.text("parent", "example"),
            "parent\nexample"
        );
    }

    #[test]
    fn expanded_dev_query_maps_file_output_to_cat_vocabulary() {
        let query = "read a file to standard output";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::ExpandedDev),
            "read a file to standard output print contents file stdout"
        );
    }

    #[test]
    fn expanded_dev_query_maps_systemctl_restart_to_service_vocabulary() {
        let query = "restart one Linux unit with systemctl";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::ExpandedDev),
            "restart one Linux unit with systemctl start stop restart reload show status service"
        );
    }

    #[test]
    fn expanded_dev_query_maps_displayed_linux_ipv4_interfaces_to_ip_vocabulary() {
        let query = "display interface IPv4 addresses on Linux";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::ExpandedDev),
            "display interface IPv4 addresses on Linux list interfaces detailed info brief network layer"
        );
    }

    #[test]
    fn expanded_dev_query_maps_inspected_linux_ipv4_interfaces_to_ip_vocabulary() {
        let query = "inspect assigned IPv4 addresses on Linux interfaces";
        assert_eq!(
            dense_query_text(query, DenseQueryMode::ExpandedDev),
            "inspect assigned IPv4 addresses on Linux interfaces list interfaces detailed info brief network layer"
        );
    }

    #[test]
    fn expanded_dev_query_does_not_treat_pasteboard_output_as_file_contents() {
        let query = "put standard output on the Mac pasteboard";
        assert_eq!(dense_query_text(query, DenseQueryMode::ExpandedDev), query);
    }

    #[test]
    fn expanded_dev_query_leaves_unrelated_stdout_intent_unchanged() {
        let query = "show profile contents on standard output";
        assert_eq!(dense_query_text(query, DenseQueryMode::ExpandedDev), query);
    }

    #[test]
    fn expanded_dev_query_does_not_treat_destructive_file_contents_as_cat() {
        let query = "delete a file's contents";
        assert_eq!(dense_query_text(query, DenseQueryMode::ExpandedDev), query);
    }

    #[test]
    fn expanded_dev_query_does_not_match_nonstandard_output() {
        let query = "copy a file to nonstandard output";
        assert_eq!(dense_query_text(query, DenseQueryMode::ExpandedDev), query);
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
