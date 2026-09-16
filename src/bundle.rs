use crate::dense::{
    DENSE_INDEX_VERSION, MODEL_CACHE_FOLDER, MODEL_DIMENSION, MODEL_FILES, MODEL_ID,
    MODEL_MAX_LENGTH, MODEL_REVISION, MODEL_RUNTIME, validate_dense_artifact_file,
    validate_model_cache,
};
use crate::tldr_subset::{SourceMetadata, SubsetManifest, artifact_metadata, build_artifact};
use anyhow::{Context, Result, anyhow, bail};
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs;
use std::path::{Component, Path, PathBuf};

const BUNDLE_SCHEMA_VERSION: u32 = 1;
const BUNDLE_VERSION: &str = "matching-bundle-v1";
const BUNDLE_KIND: &str = "askman.matching-bundle";
const MATCHING_DATABASE: &str = "matching.db";
const BUNDLE_MANIFEST: &str = "manifest.json";
const MODEL_DIRECTORY: &str = "model-cache";
const MODEL_REFERENCE: &str = "refs/main";
const REQUIRED_PLATFORMS: [&str; 4] = ["common", "linux", "osx", "windows"];

#[derive(Debug, Clone)]
pub struct BundleBuildOptions {
    pub manifest: PathBuf,
    pub snapshot: PathBuf,
    pub model_cache: PathBuf,
    pub output: PathBuf,
    pub cli_compatibility: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BundleBuildReport {
    pub output: PathBuf,
    pub bundle_id: String,
    pub page_count: usize,
    pub example_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BundleManifest {
    pub schema_version: u32,
    pub bundle_id: String,
    pub bundle_version: String,
    pub artifact_kind: String,
    pub source: SourceMetadata,
    pub platform_selection: PlatformSelection,
    pub lexical_index: IndexComponent,
    pub dense_index: DenseComponent,
    pub corpus: IndexComponent,
    pub embedding_model: EmbeddingModel,
    pub cli_compatibility: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PlatformSelection {
    pub platforms: Vec<String>,
    pub filtering: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct IndexComponent {
    pub version: String,
    pub path: String,
    pub size_bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DenseComponent {
    pub version: String,
    pub recipe: String,
    pub path: String,
    pub size_bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EmbeddingModel {
    pub id: String,
    pub revision: String,
    pub runtime: String,
    pub dimension: usize,
    pub max_length: usize,
    pub assets: Vec<BundleAsset>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BundleAsset {
    pub path: String,
    pub size_bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Serialize)]
struct BundleIdentity<'a> {
    bundle_version: &'a str,
    cli_compatibility: &'a str,
    source: &'a SourceMetadata,
    platforms: &'a [String],
    lexical_index: &'a IndexComponent,
    dense_index: &'a DenseComponent,
    corpus: &'a IndexComponent,
    embedding_model: &'a EmbeddingModel,
}

/// Build one self-contained, offline matching bundle from provisioned inputs.
/// All validation happens in the temporary directory before publication.
pub fn build_matching_bundle(options: BundleBuildOptions) -> Result<BundleBuildReport> {
    validate_cli_compatibility(&options.cli_compatibility)?;

    let source_manifest = read_subset_manifest(&options.manifest)?;
    let output = absolute_path(&options.output)?;
    if output.exists() {
        bail!(
            "refusing to replace existing matching bundle output {}; choose a new versioned output path",
            output.display()
        );
    }
    let snapshot = fs::canonicalize(&options.snapshot).with_context(|| {
        format!(
            "failed to resolve provisioned snapshot root {}",
            options.snapshot.display()
        )
    })?;
    validate_complete_snapshot(&source_manifest, &snapshot)?;
    let model_cache = fs::canonicalize(&options.model_cache).with_context(|| {
        format!(
            "failed to resolve provisioned model cache {}",
            options.model_cache.display()
        )
    })?;
    validate_output_location(&output, &snapshot, &model_cache)?;
    validate_model_cache(&model_cache)?;

    let parent = output
        .parent()
        .ok_or_else(|| anyhow!("bundle output has no parent: {}", output.display()))?;
    fs::create_dir_all(parent)?;
    let name = output
        .file_name()
        .ok_or_else(|| anyhow!("bundle output has no file name: {}", output.display()))?
        .to_string_lossy();
    let temporary = parent.join(format!(".{name}.{}.part", std::process::id()));
    if temporary.exists() {
        bail!(
            "temporary bundle output already exists: {}",
            temporary.display()
        );
    }

    let result = build_temporary_bundle(
        &temporary,
        &options.manifest,
        &source_manifest,
        &snapshot,
        &model_cache,
        options.cli_compatibility,
    );
    match result {
        Ok(report) => {
            if let Err(error) = publish_directory(&temporary, &output) {
                let _ = fs::remove_dir_all(&temporary);
                return Err(error);
            }
            Ok(BundleBuildReport { output, ..report })
        }
        Err(error) => {
            let _ = fs::remove_dir_all(&temporary);
            Err(error)
        }
    }
}

fn build_temporary_bundle(
    temporary: &Path,
    source_manifest_path: &Path,
    source_manifest: &SubsetManifest,
    snapshot: &Path,
    model_cache: &Path,
    cli_compatibility: String,
) -> Result<BundleBuildReport> {
    fs::create_dir(temporary).with_context(|| {
        format!(
            "failed to create temporary bundle directory {}",
            temporary.display()
        )
    })?;

    let lexical_output = temporary.join("corpus.lexical.db");
    let lexical_report = build_artifact(crate::tldr_subset::BuildOptions {
        manifest: source_manifest_path.to_path_buf(),
        snapshot: snapshot.to_path_buf(),
        output: lexical_output.clone(),
    })
    .context("failed to build lexical corpus component")?;

    let model_output = temporary.join(MODEL_DIRECTORY);
    copy_model_assets(model_cache, &model_output)?;
    let dense_output = temporary.join(MATCHING_DATABASE);
    crate::dense::build_dense_index(crate::dense::DenseBuildOptions {
        artifact: lexical_output.clone(),
        model_cache: model_output.clone(),
        output: dense_output.clone(),
        recipe: crate::dense::DenseRecipe::Description,
        batch_size: crate::dense::DEFAULT_BATCH_SIZE,
    })
    .context("failed to build dense index component")?;
    fs::remove_file(&lexical_output)?;

    let database_digest = sha256_file(&dense_output)?;
    let database_size = fs::metadata(&dense_output)?.len();
    let model = model_manifest(&model_output)?;
    let source = source_metadata_from_artifact(&dense_output, source_manifest)?;
    let lexical_index = IndexComponent {
        version: format!(
            "fts5-{}-v1",
            artifact_metadata_from_file(&dense_output, "lexical_index_tokenizer")?
        ),
        path: MATCHING_DATABASE.to_string(),
        size_bytes: database_size,
        sha256: database_digest.clone(),
    };
    let corpus = IndexComponent {
        version: format!(
            "{}-corpus-v1",
            artifact_metadata_from_file(&dense_output, "parser_version")?
        ),
        path: MATCHING_DATABASE.to_string(),
        size_bytes: database_size,
        sha256: database_digest.clone(),
    };
    let dense_index = DenseComponent {
        version: artifact_metadata_from_file(&dense_output, "dense_index_version")?,
        recipe: artifact_metadata_from_file(&dense_output, "dense_embedding_text_recipe")?,
        path: MATCHING_DATABASE.to_string(),
        size_bytes: database_size,
        sha256: database_digest,
    };
    let manifest = BundleManifest {
        schema_version: BUNDLE_SCHEMA_VERSION,
        bundle_id: String::new(),
        bundle_version: BUNDLE_VERSION.to_string(),
        artifact_kind: BUNDLE_KIND.to_string(),
        source,
        platform_selection: PlatformSelection {
            platforms: REQUIRED_PLATFORMS
                .iter()
                .map(|value| value.to_string())
                .collect(),
            filtering: "query-time".to_string(),
        },
        lexical_index,
        dense_index,
        corpus,
        embedding_model: model,
        cli_compatibility,
    };
    let mut manifest = manifest;
    manifest.bundle_id = bundle_id(&manifest)?;
    write_manifest(&temporary.join(BUNDLE_MANIFEST), &manifest)?;

    validate_matching_bundle(temporary)?;
    Ok(BundleBuildReport {
        output: temporary.to_path_buf(),
        bundle_id: manifest.bundle_id,
        page_count: lexical_report.page_count,
        example_count: lexical_report.example_count,
    })
}

/// Validate every component and compatibility identity in a bundle directory.
pub fn validate_matching_bundle(bundle: &Path) -> Result<BundleManifest> {
    let root = fs::canonicalize(bundle)
        .with_context(|| format!("failed to resolve matching bundle {}", bundle.display()))?;
    let manifest_path = root.join(BUNDLE_MANIFEST);
    let manifest: BundleManifest =
        serde_json::from_slice(&fs::read(&manifest_path).with_context(|| {
            format!("failed to read bundle manifest {}", manifest_path.display())
        })?)
        .context("failed to parse matching bundle manifest")?;
    validate_manifest_shape(&manifest)?;
    if manifest.bundle_id != bundle_id(&manifest)? {
        bail!("matching bundle identity does not match its manifest");
    }

    let database = validate_bundle_component_file(
        &root,
        &manifest.corpus.path,
        manifest.corpus.size_bytes,
        &manifest.corpus.sha256,
    )?;
    let lexical = validate_bundle_component_file(
        &root,
        &manifest.lexical_index.path,
        manifest.lexical_index.size_bytes,
        &manifest.lexical_index.sha256,
    )?;
    let dense = validate_bundle_component_file(
        &root,
        &manifest.dense_index.path,
        manifest.dense_index.size_bytes,
        &manifest.dense_index.sha256,
    )?;
    if database != lexical {
        bail!("bundle corpus and lexical index must use one database");
    }
    if database != dense {
        bail!("bundle corpus and dense index must use one database");
    }
    let model_root = root.join(MODEL_DIRECTORY);
    validate_dense_artifact_file(&database, &model_root)?;
    let connection = Connection::open(&database)?;
    let source_digest = artifact_metadata(&connection, "source_digest")?;
    if source_digest != manifest.source.digest {
        bail!("bundle source digest does not match the matching database");
    }
    for (key, expected) in [
        ("source_name", manifest.source.name.as_str()),
        ("source_revision", manifest.source.revision.as_str()),
        (
            "source_digest_algorithm",
            manifest.source.digest_algorithm.as_str(),
        ),
        ("source_url", manifest.source.url.as_str()),
        ("source_attribution", manifest.source.attribution.as_str()),
        (
            "content_license_name",
            manifest.source.license.name.as_str(),
        ),
        ("content_license_url", manifest.source.license.url.as_str()),
    ] {
        if artifact_metadata(&connection, key)? != expected {
            bail!("bundle source metadata does not match the matching database: {key}");
        }
    }
    validate_database_component_versions(&manifest, &connection)?;
    let platforms = connection
        .prepare("SELECT DISTINCT platform FROM pages")?
        .query_map([], |row| row.get::<_, String>(0))?
        .collect::<rusqlite::Result<HashSet<_>>>()?;
    for platform in REQUIRED_PLATFORMS {
        if !platforms.contains(platform) {
            bail!("matching bundle is missing the {platform} platform page set");
        }
    }
    validate_model_manifest(&root, &manifest.embedding_model)?;
    Ok(manifest)
}

fn validate_manifest_shape(manifest: &BundleManifest) -> Result<()> {
    if manifest.schema_version != BUNDLE_SCHEMA_VERSION {
        bail!("unsupported matching bundle schema version");
    }
    if manifest.bundle_version != BUNDLE_VERSION {
        bail!("unsupported matching bundle version");
    }
    if manifest.artifact_kind != BUNDLE_KIND {
        bail!("unsupported matching bundle kind");
    }
    validate_cli_compatibility(&manifest.cli_compatibility)?;
    validate_platform_selection(&manifest.platform_selection)?;
    validate_dense_model_metadata(manifest)?;
    if manifest.embedding_model.assets.len() != MODEL_FILES.len() + 1 {
        bail!("matching bundle embedding model asset inventory is incomplete");
    }
    Ok(())
}

fn validate_bundle_component_file(
    root: &Path,
    relative: &str,
    expected_size: u64,
    expected_sha256: &str,
) -> Result<PathBuf> {
    validate_relative_path(relative)?;
    validate_sha256(expected_sha256)?;
    let path = root.join(relative);
    let canonical = fs::canonicalize(&path)
        .with_context(|| format!("bundle component is missing: {relative}"))?;
    if !canonical.starts_with(root) {
        bail!("bundle component escapes bundle root: {relative}");
    }
    if !canonical.is_file() {
        bail!("bundle component is not a regular file: {relative}");
    }
    let size = fs::metadata(&canonical)?.len();
    if size != expected_size {
        bail!("bundle component size mismatch: {relative}");
    }
    if sha256_file(&canonical)? != expected_sha256 {
        bail!("bundle component digest mismatch: {relative}");
    }
    Ok(canonical)
}

fn validate_model_manifest(root: &Path, model: &EmbeddingModel) -> Result<()> {
    let mut paths = HashSet::new();
    for asset in &model.assets {
        validate_relative_path(&asset.path)?;
        if !paths.insert(asset.path.clone()) {
            bail!("duplicate bundle model asset: {}", asset.path);
        }
        let path = root.join(&asset.path);
        let canonical = fs::canonicalize(&path)?;
        if !canonical.starts_with(root) {
            bail!("bundle model asset escapes bundle root: {}", asset.path);
        }
        if !canonical.is_file() {
            bail!("bundle model asset is not a regular file: {}", asset.path);
        }
        if fs::metadata(&canonical)?.len() != asset.size_bytes {
            bail!("bundle model asset size mismatch: {}", asset.path);
        }
        if sha256_file(&canonical)? != asset.sha256 {
            bail!("bundle model asset digest mismatch: {}", asset.path);
        }
    }
    let expected_paths = std::iter::once(format!(
        "{MODEL_DIRECTORY}/{MODEL_CACHE_FOLDER}/{MODEL_REFERENCE}"
    ))
    .chain(MODEL_FILES.iter().map(|(file, _)| {
        format!("{MODEL_DIRECTORY}/{MODEL_CACHE_FOLDER}/snapshots/{MODEL_REVISION}/{file}")
    }))
    .collect::<HashSet<_>>();
    if paths != expected_paths {
        bail!("matching bundle embedding model asset inventory is incompatible");
    }
    Ok(())
}

fn validate_platform_selection(selection: &PlatformSelection) -> Result<()> {
    let expected = REQUIRED_PLATFORMS
        .iter()
        .map(|value| value.to_string())
        .collect::<Vec<_>>();
    if selection.platforms != expected {
        bail!("matching bundle platform list is incompatible");
    }
    if selection.filtering != "query-time" {
        bail!("matching bundle platform filtering policy is incompatible");
    }
    Ok(())
}

fn validate_dense_model_metadata(manifest: &BundleManifest) -> Result<()> {
    if manifest.dense_index.version != DENSE_INDEX_VERSION {
        bail!("matching bundle dense index version is incompatible");
    }
    validate_embedding_model_metadata(&manifest.embedding_model)
}

fn validate_embedding_model_metadata(model: &EmbeddingModel) -> Result<()> {
    if model.id != MODEL_ID {
        bail!("matching bundle embedding model ID is incompatible");
    }
    if model.revision != MODEL_REVISION {
        bail!("matching bundle embedding model revision is incompatible");
    }
    if model.runtime != MODEL_RUNTIME {
        bail!("matching bundle embedding model runtime is incompatible");
    }
    if model.dimension != MODEL_DIMENSION {
        bail!("matching bundle embedding model dimension is incompatible");
    }
    if model.max_length != MODEL_MAX_LENGTH {
        bail!("matching bundle embedding model max length is incompatible");
    }
    Ok(())
}

fn validate_cli_compatibility(value: &str) -> Result<()> {
    let Some(version) = value.strip_prefix("askman=") else {
        bail!("CLI compatibility must use the format askman=<version>");
    };
    if version.is_empty() {
        bail!("CLI compatibility version must be non-empty");
    }
    if version.chars().any(char::is_whitespace) {
        bail!("CLI compatibility version must contain no whitespace");
    }
    Ok(())
}

fn validate_complete_snapshot(manifest: &SubsetManifest, snapshot: &Path) -> Result<()> {
    let mut declared = manifest
        .files
        .iter()
        .map(|path| path.replace('\\', "/"))
        .collect::<HashSet<_>>();
    declared.extend(
        manifest
            .exclusions
            .iter()
            .map(|exclusion| exclusion.path.replace('\\', "/")),
    );
    let mut discovered = HashSet::new();
    for platform in REQUIRED_PLATFORMS {
        let platform_root = snapshot.join(&manifest.pages_root).join(platform);
        if !platform_root.is_dir() {
            bail!("complete matching snapshot is missing platform directory: {platform}");
        }
        collect_snapshot_pages(&platform_root, snapshot, &mut discovered)?;
    }
    if declared != discovered {
        let missing = discovered
            .difference(&declared)
            .cloned()
            .collect::<Vec<_>>();
        let unexpected = declared
            .difference(&discovered)
            .cloned()
            .collect::<Vec<_>>();
        bail!(
            "complete matching snapshot file selection is incompatible; missing from manifest: {}; not present in snapshot: {}",
            display_paths(&missing),
            display_paths(&unexpected)
        );
    }
    Ok(())
}

fn collect_snapshot_pages(
    directory: &Path,
    snapshot: &Path,
    discovered: &mut HashSet<String>,
) -> Result<()> {
    let mut entries = fs::read_dir(directory)
        .with_context(|| {
            format!(
                "failed to enumerate snapshot directory {}",
                directory.display()
            )
        })?
        .collect::<std::io::Result<Vec<_>>>()?;
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let path = entry.path();
        let canonical = fs::canonicalize(&path)
            .with_context(|| format!("failed to resolve snapshot entry {}", path.display()))?;
        if !canonical.starts_with(snapshot) {
            bail!("snapshot entry escapes snapshot root: {}", path.display());
        }
        if canonical.is_dir() {
            collect_snapshot_pages(&canonical, snapshot, discovered)?;
            continue;
        }
        if is_snapshot_page(&canonical) {
            let relative = canonical
                .strip_prefix(snapshot)
                .map_err(|_| anyhow!("snapshot page is outside snapshot root"))?
                .to_str()
                .ok_or_else(|| anyhow!("snapshot page path is not UTF-8: {}", canonical.display()))?
                .replace('\\', "/");
            discovered.insert(relative);
        }
    }
    Ok(())
}

fn display_paths(paths: &[String]) -> String {
    if paths.is_empty() {
        "none".to_string()
    } else {
        let mut paths = paths.to_vec();
        paths.sort();
        paths.join(", ")
    }
}

fn is_snapshot_page(path: &Path) -> bool {
    path.is_file() && path.extension().and_then(|value| value.to_str()) == Some("md")
}

fn model_manifest(model_root: &Path) -> Result<EmbeddingModel> {
    let mut assets = Vec::with_capacity(MODEL_FILES.len() + 1);
    let reference = model_root.join(MODEL_CACHE_FOLDER).join(MODEL_REFERENCE);
    assets.push(bundle_asset(
        &reference,
        &format!("{MODEL_DIRECTORY}/{MODEL_CACHE_FOLDER}/{MODEL_REFERENCE}"),
    )?);
    let snapshot = model_root
        .join(MODEL_CACHE_FOLDER)
        .join("snapshots")
        .join(MODEL_REVISION);
    for (file, _) in MODEL_FILES {
        assets.push(bundle_asset(
            &snapshot.join(file),
            &format!("{MODEL_DIRECTORY}/{MODEL_CACHE_FOLDER}/snapshots/{MODEL_REVISION}/{file}"),
        )?);
    }
    Ok(EmbeddingModel {
        id: MODEL_ID.to_string(),
        revision: MODEL_REVISION.to_string(),
        runtime: MODEL_RUNTIME.to_string(),
        dimension: MODEL_DIMENSION,
        max_length: MODEL_MAX_LENGTH,
        assets,
    })
}

fn bundle_asset(path: &Path, relative: &str) -> Result<BundleAsset> {
    Ok(BundleAsset {
        path: relative.to_string(),
        size_bytes: fs::metadata(path)?.len(),
        sha256: sha256_file(path)?,
    })
}

fn copy_model_assets(source_cache: &Path, destination: &Path) -> Result<()> {
    let source_root = source_cache.join(MODEL_CACHE_FOLDER);
    let destination_root = destination.join(MODEL_CACHE_FOLDER);
    fs::create_dir_all(destination_root.join("refs"))?;
    fs::create_dir_all(destination_root.join("snapshots").join(MODEL_REVISION))?;
    fs::copy(
        source_root.join(MODEL_REFERENCE),
        destination_root.join(MODEL_REFERENCE),
    )?;
    for (file, _) in MODEL_FILES {
        fs::copy(
            source_root
                .join("snapshots")
                .join(MODEL_REVISION)
                .join(file),
            destination_root
                .join("snapshots")
                .join(MODEL_REVISION)
                .join(file),
        )?;
    }
    Ok(())
}

fn source_metadata_from_artifact(path: &Path, declared: &SubsetManifest) -> Result<SourceMetadata> {
    let connection = Connection::open(path)?;
    let digest = artifact_metadata(&connection, "source_digest")?;
    let mut source = declared.source.clone();
    source.digest = digest;
    Ok(source)
}

fn validate_database_component_versions(
    manifest: &BundleManifest,
    connection: &Connection,
) -> Result<()> {
    let expected_lexical_version = format!(
        "fts5-{}-v1",
        artifact_metadata(connection, "lexical_index_tokenizer")?
    );
    if manifest.lexical_index.version != expected_lexical_version {
        bail!("bundle lexical index version does not match the matching database");
    }

    let expected_corpus_version = format!(
        "{}-corpus-v1",
        artifact_metadata(connection, "parser_version")?
    );
    if manifest.corpus.version != expected_corpus_version {
        bail!("bundle corpus version does not match the matching database");
    }

    let expected_dense_recipe = artifact_metadata(connection, "dense_embedding_text_recipe")?;
    if manifest.dense_index.recipe != expected_dense_recipe {
        bail!("bundle dense recipe does not match the matching database");
    }
    Ok(())
}

fn validate_output_location(output: &Path, snapshot: &Path, model_cache: &Path) -> Result<()> {
    if output.starts_with(snapshot) {
        bail!("bundle output must be outside the provisioned snapshot");
    }
    if output.starts_with(model_cache) {
        bail!("bundle output must be outside the provisioned model cache");
    }
    Ok(())
}

fn artifact_metadata_from_file(path: &Path, key: &str) -> Result<String> {
    let connection = Connection::open(path)?;
    artifact_metadata(&connection, key)
}

fn read_subset_manifest(path: &Path) -> Result<SubsetManifest> {
    let bytes =
        fs::read(path).with_context(|| format!("failed to read manifest {}", path.display()))?;
    serde_json::from_slice(&bytes).context("failed to parse source manifest")
}

fn write_manifest(path: &Path, manifest: &BundleManifest) -> Result<()> {
    let mut bytes = serde_json::to_vec_pretty(manifest)?;
    bytes.push(b'\n');
    fs::write(path, bytes)
        .with_context(|| format!("failed to write bundle manifest {}", path.display()))
}

fn bundle_id(manifest: &BundleManifest) -> Result<String> {
    let identity = BundleIdentity {
        bundle_version: &manifest.bundle_version,
        cli_compatibility: &manifest.cli_compatibility,
        source: &manifest.source,
        platforms: &manifest.platform_selection.platforms,
        lexical_index: &manifest.lexical_index,
        dense_index: &manifest.dense_index,
        corpus: &manifest.corpus,
        embedding_model: &manifest.embedding_model,
    };
    Ok(format!(
        "{}:{:x}",
        BUNDLE_VERSION,
        Sha256::digest(serde_json::to_vec(&identity)?)
    ))
}

fn validate_relative_path(path: &str) -> Result<()> {
    let candidate = Path::new(path);
    if path.is_empty() {
        bail!("bundle path is not a safe relative path: {path}");
    }
    if candidate.is_absolute() {
        bail!("bundle path is not a safe relative path: {path}");
    }
    if contains_unsafe_path_component(candidate) {
        bail!("bundle path is not a safe relative path: {path}");
    }
    Ok(())
}

fn contains_unsafe_path_component(path: &Path) -> bool {
    path.components().any(|component| {
        matches!(
            component,
            Component::CurDir | Component::ParentDir | Component::RootDir | Component::Prefix(_)
        )
    })
}

fn validate_sha256(value: &str) -> Result<()> {
    if value.len() != 64 {
        bail!("bundle SHA256 digest is invalid");
    }
    if !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        bail!("bundle SHA256 digest is invalid");
    }
    Ok(())
}

fn publish_directory(temporary: &Path, output: &Path) -> Result<()> {
    if output.exists() {
        bail!(
            "refusing to replace existing matching bundle output {}; choose a new versioned output path",
            output.display()
        );
    }
    fs::rename(temporary, output)
        .with_context(|| format!("failed to publish matching bundle {}", output.display()))
}

fn absolute_path(path: &Path) -> Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()?.join(path)
    };
    if let Some(parent) = absolute.parent() {
        if parent.exists() {
            return Ok(fs::canonicalize(parent)?.join(
                absolute
                    .file_name()
                    .ok_or_else(|| anyhow!("path has no file name"))?,
            ));
        }
    }
    Ok(absolute)
}

fn sha256_file(path: &Path) -> Result<String> {
    Ok(format!("{:x}", Sha256::digest(fs::read(path)?)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundle_identity_is_stable_for_unchanged_inputs() {
        let source = SourceMetadata {
            name: "tldr-pages".to_string(),
            revision: "snapshot-1".to_string(),
            digest_algorithm: "sha256".to_string(),
            digest: "a".repeat(64),
            url: "https://github.com/tldr-pages/tldr".to_string(),
            attribution: "Content from tldr-pages.".to_string(),
            license: crate::tldr_subset::LicenseMetadata {
                name: "MIT".to_string(),
                url: "https://github.com/tldr-pages/tldr/blob/main/LICENSE.md".to_string(),
            },
        };
        let component = IndexComponent {
            version: "component-v1".to_string(),
            path: MATCHING_DATABASE.to_string(),
            size_bytes: 10,
            sha256: "b".repeat(64),
        };
        let manifest = BundleManifest {
            schema_version: BUNDLE_SCHEMA_VERSION,
            bundle_id: String::new(),
            bundle_version: BUNDLE_VERSION.to_string(),
            artifact_kind: BUNDLE_KIND.to_string(),
            source,
            platform_selection: PlatformSelection {
                platforms: REQUIRED_PLATFORMS
                    .iter()
                    .map(|value| value.to_string())
                    .collect(),
                filtering: "query-time".to_string(),
            },
            lexical_index: component.clone(),
            dense_index: DenseComponent {
                version: DENSE_INDEX_VERSION.to_string(),
                recipe: "description".to_string(),
                path: MATCHING_DATABASE.to_string(),
                size_bytes: 10,
                sha256: "b".repeat(64),
            },
            corpus: component,
            embedding_model: EmbeddingModel {
                id: MODEL_ID.to_string(),
                revision: MODEL_REVISION.to_string(),
                runtime: MODEL_RUNTIME.to_string(),
                dimension: MODEL_DIMENSION,
                max_length: MODEL_MAX_LENGTH,
                assets: Vec::new(),
            },
            cli_compatibility: "askman=0.3.3".to_string(),
        };
        let first = bundle_id(&manifest).unwrap();
        let second = bundle_id(&manifest.clone()).unwrap();
        assert_eq!(first, second);

        let mut changed_compatibility = manifest;
        changed_compatibility.cli_compatibility = "askman=0.3.4".to_string();
        assert_ne!(first, bundle_id(&changed_compatibility).unwrap());
    }

    #[test]
    fn bundle_paths_reject_parent_and_absolute_components() {
        assert!(validate_relative_path("../matching.db").is_err());
        assert!(validate_relative_path("/tmp/matching.db").is_err());
        assert!(validate_relative_path("matching.db").is_ok());
    }

    #[test]
    fn cli_compatibility_requires_an_askman_version_without_whitespace() {
        assert!(validate_cli_compatibility("askman=0.3.3").is_ok());
        for invalid in ["", "0.3.3", "askman=", "askman=0.3 3"] {
            assert!(validate_cli_compatibility(invalid).is_err(), "{invalid:?}");
        }
    }

    #[test]
    fn existing_bundle_is_refused_without_changing_it() {
        let directory = tempfile::tempdir().unwrap();
        let output = directory.path().join("matching-bundle");
        fs::create_dir(&output).unwrap();
        let marker = output.join("marker");
        fs::write(&marker, b"previous bundle").unwrap();

        let error = build_matching_bundle(BundleBuildOptions {
            manifest: "tests/fixtures/tldr-full-corpus/manifest.json".into(),
            snapshot: "tests/fixtures/tldr-full-corpus".into(),
            model_cache: directory.path().join("missing-model-cache"),
            output: output.clone(),
            cli_compatibility: "askman=0.3.3".to_string(),
        })
        .unwrap_err()
        .to_string();

        assert!(error.contains("refusing to replace existing matching bundle output"));
        assert_eq!(fs::read(&marker).unwrap(), b"previous bundle");
    }

    #[test]
    fn bundle_rejects_a_manifest_that_omits_a_snapshot_page() {
        let directory = tempfile::tempdir().unwrap();
        let source_manifest =
            fs::read_to_string("tests/fixtures/tldr-full-corpus/manifest.json").unwrap();
        let mut manifest: serde_json::Value = serde_json::from_str(&source_manifest).unwrap();
        manifest["files"]
            .as_array_mut()
            .unwrap()
            .retain(|path| path.as_str() != Some("pages/windows/printf.md"));
        let manifest_path = directory.path().join("manifest.json");
        fs::write(
            &manifest_path,
            serde_json::to_vec_pretty(&manifest).unwrap(),
        )
        .unwrap();

        let error = build_matching_bundle(BundleBuildOptions {
            manifest: manifest_path,
            snapshot: "tests/fixtures/tldr-full-corpus".into(),
            model_cache: directory.path().join("missing-model-cache"),
            output: directory.path().join("matching-bundle"),
            cli_compatibility: "askman=0.3.3".to_string(),
        })
        .unwrap_err()
        .to_string();

        assert!(
            error.contains("missing from manifest: pages/windows/printf.md"),
            "{error}"
        );
        assert!(!directory.path().join("matching-bundle").exists());
    }
}
