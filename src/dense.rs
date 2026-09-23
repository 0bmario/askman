use crate::tldr_subset::{
    artifact_metadata, process_peak_memory_bytes, selected_page_ids, validate_artifact,
};
use anyhow::{Context, Result, anyhow, bail};
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use rusqlite::{Connection, Row, params, params_from_iter};
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
pub const DENSE_INDEX_VERSION: &str = "dense-vec0-v2";
pub const DENSE_RETRIEVAL_STRATEGY: &str = "partitioned-knn-v1";
pub const DENSE_PARTITION_KEY: &str = "platform";
pub const DENSE_ROWID_MAPPING: &str = "example_dense.dense_rowid-v1";
pub const DENSE_PARTITIONS: [&str; 4] = ["common", "linux", "osx", "windows"];
pub const DENSE_PARTITIONS_JSON: &str = "[\"common\",\"linux\",\"osx\",\"windows\"]";
pub const DENSE_NORMALIZATION: &str = "l2";
pub const DENSE_DISTANCE_METRIC: &str = "cosine";
pub const DENSE_RECIPE_VERSION: &str = "dense-text-v1";
pub const DEFAULT_BATCH_SIZE: usize = 32;
const DENSE_QUERY_MODE_ENV: &str = "ASKMAN_DENSE_QUERY_MODE";
// sqlite-vec rejects KNN limits above this hard maximum. Each required
// platform partition is queried independently with this bound. If the union
// does not contain the requested number of unique pages, retrieval falls back
// to SQL scalar distances over the selected pages.
const MAX_KNN_BATCH_SIZE: usize = 4096;
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
    #[serde(default)]
    platform_explicit: bool,
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
    platform: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct DensePartitionStats {
    raw_count: usize,
    unique_page_count: usize,
    saturated: bool,
}

#[derive(Debug, Clone)]
struct DensePartitionCandidates {
    partition: String,
    stats: DensePartitionStats,
    candidates: Vec<DenseCandidate>,
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
                        request.platform_explicit,
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
        platform_explicit: bool,
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
        let query_blob = embedding_blob(&query_vector);
        let mut partition_results = Vec::new();
        for partition in required_dense_partitions(platform) {
            partition_results.push(self.query_knn_partition(&query_blob, &selected, partition)?);
        }
        let knn_candidates = partition_results
            .iter()
            .flat_map(|result| result.candidates.iter().cloned())
            .collect::<Vec<_>>();
        let ranked = rank_dense_candidates(
            knn_candidates,
            &selected,
            platform,
            platform_explicit,
            limit,
        );
        if ranked.len() == limit
            && partition_union_proves_completeness(
                &partition_results,
                platform,
                platform_explicit,
                limit,
            )
        {
            return Ok(ranked);
        }

        // A partition KNN batch is bounded by sqlite-vec's hard 4096-row
        // limit. If the required partition union cannot supply the requested
        // page budget, compute exact distances in SQLite over the selected
        // pages. This path deliberately never decodes vector blobs in Rust.
        self.sql_distance_candidates(&query_blob, &selected, platform, platform_explicit, limit)
    }

    fn query_knn_partition(
        &self,
        query_blob: &[u8],
        selected: &HashSet<String>,
        partition: &str,
    ) -> Result<DensePartitionCandidates> {
        query_knn_partition(&self.connection, query_blob, selected, partition)
    }

    fn sql_distance_candidates(
        &self,
        query_blob: &[u8],
        selected: &HashSet<String>,
        platform: &str,
        platform_explicit: bool,
        limit: usize,
    ) -> Result<Vec<DenseCandidate>> {
        sql_distance_candidates(
            &self.connection,
            query_blob,
            selected,
            platform,
            platform_explicit,
            limit,
        )
    }
}

fn query_knn_partition(
    connection: &Connection,
    query_blob: &[u8],
    selected: &HashSet<String>,
    partition: &str,
) -> Result<DensePartitionCandidates> {
    let mut statement = connection.prepare(
        "SELECT dense.rowid, dense.example_id, dense.distance
         FROM example_dense_index AS dense
         WHERE dense.embedding MATCH ?1
           AND dense.k = ?2
           AND dense.platform = ?3
         ORDER BY dense.distance
         ",
    )?;
    let rows = statement.query_map(
        params![query_blob, MAX_KNN_BATCH_SIZE as i64, partition],
        |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, f64>(2)?,
            ))
        },
    )?;
    let mut details = connection.prepare(
        "SELECT e.example_id, e.page_id, p.command, e.command,
                p.description, e.description, p.source_path, p.source_ref,
                p.source_revision, p.platform, p.page_position, e.position
         FROM examples AS e
         JOIN pages AS p ON p.page_id = e.page_id
         WHERE e.example_id = ?1",
    )?;
    let mut candidates = Vec::new();
    let mut raw_count = 0;
    for row in rows {
        raw_count += 1;
        let (_rowid, example_id, distance) = row?;
        let mut candidate =
            details.query_row(params![example_id], dense_candidate_details_from_row)?;
        candidate.ranking_score = distance;
        if selected.contains(&candidate.page_id) {
            candidates.push(candidate);
        }
    }
    candidates.sort_by(|left, right| {
        left.ranking_score
            .total_cmp(&right.ranking_score)
            .then_with(|| left.example_id.cmp(&right.example_id))
    });
    let unique_page_count = candidates
        .iter()
        .map(|candidate| candidate.page_id.as_str())
        .collect::<HashSet<_>>()
        .len();
    Ok(DensePartitionCandidates {
        partition: partition.to_string(),
        stats: DensePartitionStats {
            raw_count,
            unique_page_count,
            saturated: raw_count >= MAX_KNN_BATCH_SIZE,
        },
        candidates,
    })
}

fn sql_distance_candidates(
    connection: &Connection,
    query_blob: &[u8],
    selected: &HashSet<String>,
    platform: &str,
    platform_explicit: bool,
    limit: usize,
) -> Result<Vec<DenseCandidate>> {
    let mut page_ids = selected.iter().cloned().collect::<Vec<_>>();
    page_ids.sort();
    let placeholders = (0..page_ids.len())
        .map(|index| format!("?{}", index + 2))
        .collect::<Vec<_>>()
        .join(", ");
    let query = format!(
        "SELECT dense.example_id, e.page_id, p.command, e.command,
                p.description, e.description, p.source_path, p.source_ref,
                p.source_revision, p.platform, p.page_position, e.position,
                vec_distance_cosine(?1, dense.embedding)
         FROM example_dense AS dense
         JOIN examples AS e ON e.example_id = dense.example_id
         JOIN pages AS p ON p.page_id = e.page_id
         WHERE e.page_id IN ({placeholders})
         ORDER BY vec_distance_cosine(?1, dense.embedding), dense.dense_rowid"
    );
    let mut values = Vec::with_capacity(page_ids.len() + 1);
    values.push(rusqlite::types::Value::Blob(query_blob.to_vec()));
    values.extend(page_ids.into_iter().map(rusqlite::types::Value::Text));
    let mut statement = connection.prepare(&query)?;
    let rows = statement.query_map(params_from_iter(values), dense_candidate_from_row)?;
    let mut candidates = Vec::new();
    for row in rows {
        candidates.push(row?);
    }
    Ok(rank_dense_candidates(
        candidates,
        selected,
        platform,
        platform_explicit,
        limit,
    ))
}

fn dense_candidate_from_row(row: &Row<'_>) -> rusqlite::Result<DenseCandidate> {
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
        ranking_score: row.get(12)?,
    })
}

fn dense_candidate_details_from_row(row: &Row<'_>) -> rusqlite::Result<DenseCandidate> {
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
        ranking_score: 0.0,
    })
}

fn required_dense_partitions(platform: &str) -> Vec<&str> {
    if platform == "common" {
        vec!["common"]
    } else {
        vec![platform, "common"]
    }
}

fn partition_union_proves_completeness(
    partitions: &[DensePartitionCandidates],
    platform: &str,
    platform_explicit: bool,
    limit: usize,
) -> bool {
    if limit == 0 {
        return true;
    }
    if !platform_explicit {
        // Host-default ranking merges by distance. Every saturated partition
        // must independently expose enough unique pages for a global top-k;
        // an unsaturated partition returned its complete vector population.
        return partitions.iter().all(|partition| {
            !partition.stats.saturated || partition.stats.unique_page_count >= limit
        });
    }

    let Some(target) = partitions
        .iter()
        .find(|partition| partition.partition == platform)
        .or_else(|| partitions.first())
    else {
        return false;
    };
    if target.stats.unique_page_count >= limit {
        // Explicit platform precedence means target pages alone prove the
        // result; common pages cannot outrank them.
        return true;
    }
    if target.stats.saturated {
        // A saturated target with too few unique pages may hide additional
        // target pages behind duplicate examples. Common cannot prove target
        // precedence, so use the exact SQL fallback.
        return false;
    }

    let remaining = limit.saturating_sub(target.stats.unique_page_count);
    let Some(common) = partitions.iter().find(|partition| {
        partition.partition == "common" && partition.partition != target.partition
    }) else {
        return false;
    };
    // Target was unsaturated (complete). Common may be saturated, but then
    // its observed unique-page count must cover the remaining budget.
    common.stats.unique_page_count >= remaining
}

fn rank_dense_candidates(
    mut candidates: Vec<DenseCandidate>,
    selected: &HashSet<String>,
    platform: &str,
    platform_explicit: bool,
    limit: usize,
) -> Vec<DenseCandidate> {
    candidates.retain(|candidate| selected.contains(&candidate.page_id));
    candidates.sort_by(|left, right| {
        let target_order = if platform_explicit {
            (right.platform == platform).cmp(&(left.platform == platform))
        } else {
            std::cmp::Ordering::Equal
        };
        target_order
            .then_with(|| left.ranking_score.total_cmp(&right.ranking_score))
            .then_with(|| left.page_position.cmp(&right.page_position))
            .then_with(|| left.example_position.cmp(&right.example_position))
            .then_with(|| left.example_id.cmp(&right.example_id))
    });
    let mut seen_pages = HashSet::new();
    candidates
        .into_iter()
        .filter(|candidate| seen_pages.insert(candidate.page_id.clone()))
        .take(limit)
        .collect()
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

    // macOS pasteboard direction: place/copy/send/pipe/put something ONTO the
    // clipboard is `pbcopy`; reading FROM it is not — queries with extraction
    // phrasing ("from the clipboard") stay unexpanded.
    let mentions_clipboard =
        query_words.contains(&"clipboard") || query_words.contains(&"pasteboard");
    let requests_clipboard_write = ["copy", "send", "place", "pipe", "put"]
        .iter()
        .any(|term| query_words.contains(term));
    let names_extraction_source = query_words.contains(&"from");
    if mentions_clipboard && requests_clipboard_write && !names_extraction_source {
        additions.push("pbcopy place the results of a specific command in the clipboard");
    }

    // File copy with a destination: bias toward the copy command's
    // file-to-path examples instead of adjacent same-verb pages (move, cp
    // variants, directory-recursive examples). "make a second copy" is a
    // duplicate intent without an explicit destination word.
    let requests_file_copy = ["copy", "duplicate", "put"]
        .iter()
        .any(|term| query_words.contains(term));
    let names_moved_object = query_words.contains(&"file");
    let names_destination = ["another", "destination", "folder", "path", "directory"]
        .iter()
        .any(|term| query_words.contains(term))
        || query_words
            .windows(2)
            .any(|words| words == ["second", "copy"]);
    if requests_file_copy && names_moved_object && names_destination {
        additions.push("copy file another location directory destination");
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
             dense_rowid INTEGER PRIMARY KEY NOT NULL,
             example_id TEXT UNIQUE NOT NULL REFERENCES examples(example_id),
             platform TEXT NOT NULL CHECK(platform IN ('common', 'linux', 'osx', 'windows')),
             embedding_text TEXT NOT NULL,
             embedding BLOB NOT NULL,
             dimension INTEGER NOT NULL,
             normalization TEXT NOT NULL
         );",
    )?;
    transaction.execute_batch(&format!(
        "CREATE VIRTUAL TABLE example_dense_index USING vec0(
             embedding float[{MODEL_DIMENSION}] distance_metric={DENSE_DISTANCE_METRIC},
             platform text partition key,
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
        (
            "dense_retrieval_strategy",
            DENSE_RETRIEVAL_STRATEGY.to_string(),
        ),
        ("dense_partition_key", DENSE_PARTITION_KEY.to_string()),
        ("dense_partitions", DENSE_PARTITIONS_JSON.to_string()),
        ("dense_rowid_mapping", DENSE_ROWID_MAPPING.to_string()),
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
                     dense_rowid, example_id, platform, embedding_text, embedding,
                     dimension, normalization
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    row_id,
                    row.example_id,
                    row.platform,
                    texts[offset],
                    blob,
                    MODEL_DIMENSION as i64,
                    DENSE_NORMALIZATION,
                ],
            )?;
            transaction.execute(
                "INSERT INTO example_dense_index(rowid, embedding, platform, example_id)
                 VALUES (?1, ?2, ?3, ?4)",
                params![
                    row_id,
                    embedding_blob(&embedding),
                    row.platform,
                    row.example_id
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
        "SELECT e.example_id, p.description, e.description, p.platform
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
            platform: row.get(3)?,
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
        (
            "dense_retrieval_strategy",
            DENSE_RETRIEVAL_STRATEGY.to_string(),
        ),
        ("dense_partition_key", DENSE_PARTITION_KEY.to_string()),
        ("dense_partitions", DENSE_PARTITIONS_JSON.to_string()),
        ("dense_rowid_mapping", DENSE_ROWID_MAPPING.to_string()),
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
    let dense_rows = connection
        .prepare(
            "SELECT dense.dense_rowid, dense.example_id, dense.platform, dense.embedding,
                    p.platform
             FROM example_dense AS dense
             JOIN examples AS e ON e.example_id = dense.example_id
             JOIN pages AS p ON p.page_id = e.page_id
             ORDER BY dense.dense_rowid",
        )?
        .query_map([], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Vec<u8>>(3)?,
                row.get::<_, String>(4)?,
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if dense_rows.len() != dense_ids.len() {
        bail!("dense row mapping coverage does not match stored vectors");
    }
    let mut dense_by_id = HashMap::new();
    let mut dense_by_rowid = HashMap::new();
    for (expected, (rowid, example_id, platform, embedding, page_platform)) in
        dense_rows.into_iter().enumerate()
    {
        let expected_rowid = (expected + 1) as i64;
        if rowid != expected_rowid {
            bail!("dense row mapping is not contiguous: expected {expected_rowid}, got {rowid}");
        }
        if !DENSE_PARTITIONS.contains(&platform.as_str()) || platform != page_platform {
            bail!("dense row mapping platform mismatch for {example_id}");
        }
        validate_embedding_blob(&embedding, &example_id)?;
        dense_by_id.insert(
            example_id.clone(),
            (rowid, platform.clone(), embedding.clone()),
        );
        dense_by_rowid.insert(rowid, (example_id, platform, embedding));
    }
    let index_rows = connection
        .prepare(
            "SELECT rowid, example_id, platform, embedding
             FROM example_dense_index
             ORDER BY rowid",
        )?
        .query_map([], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Vec<u8>>(3)?,
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if index_rows.len() != dense_ids.len() {
        bail!("dense vector index row coverage does not match stored vectors");
    }
    let mut index_ids = HashSet::new();
    for (expected, (rowid, example_id, platform, embedding)) in index_rows.into_iter().enumerate() {
        let expected_rowid = (expected + 1) as i64;
        if rowid != expected_rowid {
            bail!(
                "dense vector index rowids are not contiguous: expected {expected_rowid}, got {rowid}"
            );
        }
        if !index_ids.insert(example_id.clone()) {
            bail!("dense vector index contains a duplicate example identity: {example_id}");
        }
        validate_embedding_blob(&embedding, &example_id)?;
        let Some((dense_rowid, dense_platform, dense_embedding)) = dense_by_id.get(&example_id)
        else {
            bail!("dense vector index contains an unknown example identity: {example_id}");
        };
        if *dense_rowid != rowid || dense_platform != &platform || dense_embedding != &embedding {
            bail!("dense vector index payload does not match stored vector: {example_id}");
        }
        if dense_by_rowid.get(&rowid).map(|(id, _, _)| id) != Some(&example_id) {
            bail!("dense vector index rowid mapping does not match stored vector: {rowid}");
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
    let expected_partition = "platformtextpartitionkey";
    let expected_auxiliary = "+example_idtext";
    if !normalized_sql.contains(&expected_dimension)
        || !normalized_sql.contains(&expected_metric)
        || !normalized_sql.contains(expected_partition)
        || !normalized_sql.contains(expected_auxiliary)
    {
        bail!(
            "dense vector index schema is incompatible: expected {expected_dimension}, {expected_metric}, {expected_partition}, and {expected_auxiliary}"
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
    embedding_from_blob(blob, identity).map(|_| ())
}

fn embedding_from_blob(blob: &[u8], identity: &str) -> Result<Vec<f32>> {
    if blob.len() != MODEL_DIMENSION * std::mem::size_of::<f32>() {
        bail!("dense vector blob for {identity} has invalid byte length");
    }
    let values = blob
        .chunks_exact(4)
        .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
        .collect::<Vec<_>>();
    validate_embedding(&values, identity)?;
    Ok(values)
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
    TextEmbedding::try_new(
        InitOptions::new(EmbeddingModel::AllMiniLML6V2)
            .with_cache_dir(assets.cache_dir.clone())
            .with_show_download_progress(false)
            .with_max_length(MODEL_MAX_LENGTH),
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
    use std::collections::HashSet;

    fn query_fixture(rows: &[(String, String, String)]) -> (Connection, HashSet<String>, Vec<u8>) {
        register_sqlite_vec();
        let connection = Connection::open_in_memory().unwrap();
        connection
            .execute_batch(
                "CREATE TABLE pages(
                     page_id TEXT PRIMARY KEY,
                     command TEXT NOT NULL,
                     description TEXT NOT NULL,
                     source_path TEXT NOT NULL,
                     source_ref TEXT NOT NULL,
                     source_revision TEXT NOT NULL,
                     platform TEXT NOT NULL,
                     page_position INTEGER NOT NULL
                 );
                 CREATE TABLE examples(
                     example_id TEXT PRIMARY KEY,
                     page_id TEXT NOT NULL,
                     command TEXT NOT NULL,
                     description TEXT NOT NULL,
                     position INTEGER NOT NULL
                 );
                 CREATE TABLE example_dense(
                     dense_rowid INTEGER PRIMARY KEY NOT NULL,
                     example_id TEXT UNIQUE NOT NULL,
                     platform TEXT NOT NULL,
                     embedding_text TEXT NOT NULL,
                     embedding BLOB NOT NULL,
                     dimension INTEGER NOT NULL,
                     normalization TEXT NOT NULL
                 );
                 CREATE VIRTUAL TABLE example_dense_index USING vec0(
                     embedding float[384] distance_metric=cosine,
                     platform text partition key,
                     +example_id text
                 );",
            )
            .unwrap();

        let vector = vec![1.0f32; MODEL_DIMENSION]
            .into_iter()
            .map(|value| value / (MODEL_DIMENSION as f32).sqrt())
            .collect::<Vec<_>>();
        let blob = embedding_blob(&vector);
        let mut pages = HashSet::new();
        for (rowid, (example_id, page_id, platform)) in rows.iter().enumerate() {
            if pages.insert(page_id.clone()) {
                connection
                    .execute(
                        "INSERT INTO pages(
                             page_id, command, description, source_path, source_ref,
                             source_revision, platform, page_position
                         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                        params![
                            page_id,
                            page_id,
                            "page",
                            format!("pages/{platform}/{page_id}.md"),
                            "tldr-pages@test:path",
                            "test",
                            platform,
                            rowid as i64,
                        ],
                    )
                    .unwrap();
            }
            connection
                .execute(
                    "INSERT INTO examples(example_id, page_id, command, description, position)
                     VALUES (?1, ?2, ?3, ?4, ?5)",
                    params![example_id, page_id, example_id, "example", rowid as i64],
                )
                .unwrap();
            connection
                .execute(
                    "INSERT INTO example_dense(
                         dense_rowid, example_id, platform, embedding_text, embedding,
                         dimension, normalization
                     ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                    params![
                        rowid as i64 + 1,
                        example_id,
                        platform,
                        "example",
                        &blob,
                        MODEL_DIMENSION as i64,
                        DENSE_NORMALIZATION,
                    ],
                )
                .unwrap();
            connection
                .execute(
                    "INSERT INTO example_dense_index(rowid, embedding, platform, example_id)
                     VALUES (?1, ?2, ?3, ?4)",
                    params![rowid as i64 + 1, &blob, platform, example_id],
                )
                .unwrap();
        }
        (connection, pages, blob)
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
    fn expanded_dev_query_maps_pasteboard_write_intents_to_pbcopy() {
        for query in [
            "copy shell output to the macOS clipboard",
            "send terminal output to the Mac pasteboard",
            "place command results in the macOS clipboard",
            "pipe command output into the Apple clipboard",
            "put standard output on the Mac pasteboard",
        ] {
            assert!(
                dense_query_text(query, DenseQueryMode::ExpandedDev)
                    .contains("pbcopy place the results of a specific command in the clipboard"),
                "query should expand toward pbcopy: {query}"
            );
        }
    }

    #[test]
    fn expanded_dev_query_leaves_pasteboard_extraction_unexpanded() {
        let query = "print the text from the clipboard";
        assert_eq!(dense_query_text(query, DenseQueryMode::ExpandedDev), query);
    }

    #[test]
    fn expanded_dev_query_maps_file_copy_with_destination_to_copy_vocabulary() {
        for query in [
            "copy one Windows file to another path",
            "duplicate a single file in a Windows directory",
            "copy one file into a different Windows folder",
            "make a second copy of one Windows file",
            "put one Windows file at a destination path",
        ] {
            assert!(
                dense_query_text(query, DenseQueryMode::ExpandedDev)
                    .contains("copy file another location directory destination"),
                "query should expand toward the copy destination examples: {query}"
            );
        }
    }

    #[test]
    fn expanded_dev_query_leaves_directory_recursive_copy_unexpanded() {
        let query = "copy the directory recursively";
        assert_eq!(dense_query_text(query, DenseQueryMode::ExpandedDev), query);
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
    fn expanded_dev_query_maps_pasteboard_output_to_pbcopy_direction() {
        // #46 left pasteboard queries unexpanded to keep them away from
        // `cat`; the dev-split evidence (4/5 rank-1 misses ranking `pbpaste`
        // above `pbcopy`) now pins the write direction instead. Extraction
        // phrasing stays unexpanded (see the "from the clipboard" guard).
        let query = "put standard output on the Mac pasteboard";
        assert!(
            dense_query_text(query, DenseQueryMode::ExpandedDev)
                .contains("pbcopy place the results of a specific command in the clipboard")
        );
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

    #[test]
    fn dense_schema_requires_partition_key_and_stable_row_mapping() {
        let rows = vec![(
            "example-1".to_string(),
            "page-1".to_string(),
            "linux".to_string(),
        )];
        let (connection, _, _) = query_fixture(&rows);
        validate_dense_index_schema(&connection).unwrap();
        let row: (i64, String, String) = connection
            .query_row(
                "SELECT rowid, example_id, platform FROM example_dense_index",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(row, (1, "example-1".to_string(), "linux".to_string()));
        assert_eq!(required_dense_partitions("linux"), ["linux", "common"]);
        assert_eq!(required_dense_partitions("common"), ["common"]);
    }

    #[test]
    fn partitioned_knn_unions_over_4096_vectors_and_deduplicates_pages() {
        let rows = (0..5000)
            .map(|index| {
                let platform = if index < 3000 { "linux" } else { "common" };
                let page_id = format!("{platform}-page-{}", index / 2);
                (format!("example-{index}"), page_id, platform.to_string())
            })
            .collect::<Vec<_>>();
        let (connection, selected, blob) = query_fixture(&rows);
        let target_result = query_knn_partition(&connection, &blob, &selected, "linux").unwrap();
        let common_result = query_knn_partition(&connection, &blob, &selected, "common").unwrap();
        assert_eq!(target_result.stats.raw_count, 3000);
        assert!(!target_result.stats.saturated);
        assert_eq!(target_result.stats.unique_page_count, 1500);
        assert_eq!(common_result.stats.raw_count, 2000);
        assert!(!common_result.stats.saturated);
        assert_eq!(common_result.stats.unique_page_count, 1000);
        assert_eq!(target_result.candidates.len(), 3000);
        assert_eq!(common_result.candidates.len(), 2000);
        assert!(
            target_result
                .candidates
                .iter()
                .all(|candidate| candidate.platform == "linux")
        );
        assert!(
            common_result
                .candidates
                .iter()
                .all(|candidate| candidate.platform == "common")
        );

        let ranked = rank_dense_candidates(
            target_result
                .candidates
                .into_iter()
                .chain(common_result.candidates)
                .collect(),
            &selected,
            "linux",
            true,
            selected.len(),
        );
        assert_eq!(ranked.len(), 2500);
        assert_eq!(
            ranked
                .iter()
                .map(|candidate| candidate.page_id.clone())
                .collect::<HashSet<_>>()
                .len(),
            2500
        );
        assert!(
            ranked[..1500]
                .iter()
                .all(|candidate| candidate.platform == "linux")
        );
        assert!(
            ranked[1500..]
                .iter()
                .all(|candidate| candidate.platform == "common")
        );
    }

    #[test]
    fn underfilled_knn_uses_sql_cosine_fallback_and_matches_oracle() {
        let mut rows = (0..4096)
            .map(|index| {
                (
                    format!("noise-{index}"),
                    format!("noise-page-{index}"),
                    "linux".to_string(),
                )
            })
            .collect::<Vec<_>>();
        rows.extend([
            (
                "selected-a".to_string(),
                "selected-page-a".to_string(),
                "linux".to_string(),
            ),
            (
                "selected-b".to_string(),
                "selected-page-b".to_string(),
                "linux".to_string(),
            ),
        ]);
        let (connection, _, blob) = query_fixture(&rows);
        let selected =
            HashSet::from(["selected-page-a".to_string(), "selected-page-b".to_string()]);
        let knn = query_knn_partition(&connection, &blob, &selected, "linux").unwrap();
        assert_eq!(knn.stats.raw_count, MAX_KNN_BATCH_SIZE);
        assert!(knn.stats.saturated);
        assert_eq!(knn.stats.unique_page_count, 0);
        assert!(
            knn.candidates.is_empty(),
            "selected rows are outside the KNN batch"
        );

        let fallback =
            sql_distance_candidates(&connection, &blob, &selected, "linux", false, 2).unwrap();
        assert_eq!(
            fallback
                .iter()
                .map(|candidate| candidate.page_id.as_str())
                .collect::<Vec<_>>(),
            ["selected-page-a", "selected-page-b"]
        );
        for candidate in fallback {
            let oracle: f64 = connection
                .query_row(
                    "SELECT vec_distance_cosine(?1, embedding)
                     FROM example_dense WHERE example_id = ?2",
                    params![&blob, candidate.example_id],
                    |row| row.get(0),
                )
                .unwrap();
            assert!((candidate.ranking_score - oracle).abs() < 1e-6);
        }
    }

    #[test]
    fn sql_cosine_matches_knn_for_normalized_f32_vectors() {
        register_sqlite_vec();
        let connection = Connection::open_in_memory().unwrap();
        connection
            .execute_batch(
                "CREATE VIRTUAL TABLE vectors USING vec0(
                     embedding float[384] distance_metric=cosine,
                     platform text partition key,
                     +example_id text
                 );
                 CREATE TABLE scalar(example_id TEXT PRIMARY KEY, embedding BLOB NOT NULL);",
            )
            .unwrap();
        let mut first = vec![0.0f32; MODEL_DIMENSION];
        first[0] = 1.0;
        let mut second = vec![0.0f32; MODEL_DIMENSION];
        second[1] = 1.0;
        let mut query = vec![0.0f32; MODEL_DIMENSION];
        query[0] = 0.6;
        query[1] = 0.8;
        let query_blob = embedding_blob(&query);
        for (rowid, (id, vector)) in [("first", &first), ("second", &second)]
            .into_iter()
            .enumerate()
        {
            let blob = embedding_blob(vector);
            connection
                .execute(
                    "INSERT INTO vectors(rowid, embedding, platform, example_id)
                     VALUES (?1, ?2, 'linux', ?3)",
                    params![rowid as i64 + 1, &blob, id],
                )
                .unwrap();
            connection
                .execute(
                    "INSERT INTO scalar(example_id, embedding) VALUES (?1, ?2)",
                    params![id, &blob],
                )
                .unwrap();
        }
        let knn: Vec<(String, f64)> = connection
            .prepare(
                "SELECT example_id, distance FROM vectors
                 WHERE embedding MATCH ?1 AND k = ?2 AND platform = 'linux'
                 ORDER BY distance",
            )
            .unwrap()
            .query_map(params![&query_blob, 2], |row| {
                Ok((row.get(0)?, row.get(1)?))
            })
            .unwrap()
            .collect::<rusqlite::Result<_>>()
            .unwrap();
        let scalar: Vec<(String, f64)> = connection
            .prepare(
                "SELECT example_id, vec_distance_cosine(?1, embedding)
                 FROM scalar ORDER BY 2, example_id",
            )
            .unwrap()
            .query_map([&query_blob], |row| Ok((row.get(0)?, row.get(1)?)))
            .unwrap()
            .collect::<rusqlite::Result<_>>()
            .unwrap();
        assert_eq!(
            knn.iter().map(|(id, _)| id).collect::<Vec<_>>(),
            scalar.iter().map(|(id, _)| id).collect::<Vec<_>>()
        );
        for ((_, knn_distance), (_, scalar_distance)) in knn.iter().zip(scalar.iter()) {
            assert!((knn_distance - scalar_distance).abs() < 1e-6);
        }
    }

    #[test]
    fn host_default_ranking_merges_by_distance_while_explicit_prefers_target() {
        let candidate =
            |example_id: &str, page_id: &str, platform: &str, distance: f64| DenseCandidate {
                example_id: example_id.to_string(),
                page_id: page_id.to_string(),
                page_command: page_id.to_string(),
                command: page_id.to_string(),
                page_description: String::new(),
                example_description: String::new(),
                source_path: format!("pages/{platform}/{page_id}.md"),
                source_ref: String::new(),
                source_revision: String::new(),
                platform: platform.to_string(),
                page_position: 0,
                example_position: 0,
                ranking_score: distance,
            };
        let selected = HashSet::from(["target".to_string(), "common".to_string()]);
        let candidates = vec![
            candidate("target-example", "target", "linux", 0.8),
            candidate("common-example", "common", "common", 0.1),
        ];
        assert_eq!(
            rank_dense_candidates(candidates.clone(), &selected, "linux", false, 2)[0].page_id,
            "common"
        );
        assert_eq!(
            rank_dense_candidates(candidates, &selected, "linux", true, 2)[0].page_id,
            "target"
        );
    }

    #[test]
    fn completeness_rejects_duplicate_heavy_saturated_partition_even_when_union_fills_limit() {
        let candidate = |partition: &str, index: usize| DenseCandidate {
            example_id: format!("{partition}-example-{index}"),
            page_id: format!("{partition}-page-{index}"),
            page_command: String::new(),
            command: String::new(),
            page_description: String::new(),
            example_description: String::new(),
            source_path: format!("pages/{partition}/page-{index}.md"),
            source_ref: String::new(),
            source_revision: String::new(),
            platform: partition.to_string(),
            page_position: index,
            example_position: 0,
            ranking_score: index as f64,
        };
        let target = DensePartitionCandidates {
            partition: "linux".to_string(),
            stats: DensePartitionStats {
                raw_count: MAX_KNN_BATCH_SIZE,
                unique_page_count: 1,
                saturated: true,
            },
            candidates: vec![candidate("linux", 0)],
        };
        let common = DensePartitionCandidates {
            partition: "common".to_string(),
            stats: DensePartitionStats {
                raw_count: 7,
                unique_page_count: 7,
                saturated: false,
            },
            candidates: (0..7).map(|index| candidate("common", index)).collect(),
        };
        let partitions = vec![target, common];
        assert!(!partition_union_proves_completeness(
            &partitions,
            "linux",
            true,
            8
        ));
        assert!(!partition_union_proves_completeness(
            &partitions,
            "linux",
            false,
            8
        ));

        let target_complete = DensePartitionCandidates {
            partition: "linux".to_string(),
            stats: DensePartitionStats {
                raw_count: MAX_KNN_BATCH_SIZE,
                unique_page_count: 8,
                saturated: true,
            },
            candidates: (0..8).map(|index| candidate("linux", index)).collect(),
        };
        let common_saturated = DensePartitionCandidates {
            partition: "common".to_string(),
            stats: DensePartitionStats {
                raw_count: MAX_KNN_BATCH_SIZE,
                unique_page_count: 8,
                saturated: true,
            },
            candidates: (0..8).map(|index| candidate("common", index)).collect(),
        };
        assert!(partition_union_proves_completeness(
            &[target_complete, common_saturated.clone()],
            "linux",
            true,
            8
        ));
        assert!(partition_union_proves_completeness(
            &[
                DensePartitionCandidates {
                    partition: "linux".to_string(),
                    stats: DensePartitionStats {
                        raw_count: 1,
                        unique_page_count: 1,
                        saturated: false,
                    },
                    candidates: vec![candidate("linux", 0)],
                },
                common_saturated.clone(),
            ],
            "linux",
            true,
            8
        ));
        assert!(partition_union_proves_completeness(
            &[
                DensePartitionCandidates {
                    partition: "linux".to_string(),
                    stats: DensePartitionStats {
                        raw_count: 1,
                        unique_page_count: 1,
                        saturated: false,
                    },
                    candidates: vec![candidate("linux", 0)],
                },
                common_saturated,
            ],
            "linux",
            false,
            8
        ));
    }

    #[test]
    fn exact_fallback_ranking_handles_more_than_one_knn_batch() {
        let candidate =
            |example_id: String, page_id: &str, platform: &str, distance: f64| DenseCandidate {
                example_id,
                page_id: page_id.to_string(),
                page_command: page_id.to_string(),
                command: page_id.to_string(),
                page_description: String::new(),
                example_description: String::new(),
                source_path: format!("pages/{platform}/{page_id}.md"),
                source_ref: String::new(),
                source_revision: String::new(),
                platform: platform.to_string(),
                page_position: 0,
                example_position: 0,
                ranking_score: distance,
            };
        let mut candidates = (0..MAX_KNN_BATCH_SIZE)
            .map(|index| {
                candidate(
                    format!("unselected-{index}"),
                    &format!("unselected-page-{index}"),
                    "common",
                    index as f64,
                )
            })
            .collect::<Vec<_>>();
        candidates.extend([
            candidate(
                "target-duplicate-a".to_string(),
                "target-page",
                "linux",
                0.4,
            ),
            candidate(
                "target-duplicate-b".to_string(),
                "target-page",
                "linux",
                0.3,
            ),
            candidate("target-second".to_string(), "target-second", "linux", 0.5),
            candidate("common-fallback".to_string(), "common-page", "common", 0.01),
            candidate(
                "unselected-tail".to_string(),
                "unselected-tail",
                "common",
                0.0,
            ),
        ]);
        let selected = HashSet::from([
            "target-page".to_string(),
            "target-second".to_string(),
            "common-page".to_string(),
        ]);

        let ranked = rank_dense_candidates(candidates, &selected, "linux", true, 3);

        assert_eq!(ranked.len(), 3);
        assert_eq!(ranked[0].page_id, "target-page");
        assert_eq!(ranked[0].example_id, "target-duplicate-b");
        assert_eq!(ranked[1].page_id, "target-second");
        assert_eq!(ranked[2].page_id, "common-page");
    }
}
