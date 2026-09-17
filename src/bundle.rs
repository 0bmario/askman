use crate::dense::{
    DENSE_INDEX_VERSION, MODEL_CACHE_FOLDER, MODEL_DIMENSION, MODEL_FILES, MODEL_ID,
    MODEL_MAX_LENGTH, MODEL_REVISION, MODEL_RUNTIME, validate_dense_artifact_file,
    validate_model_cache,
};
use crate::tldr_subset::{
    PARSER_VERSION, SourceMetadata, SubsetManifest, artifact_metadata, build_artifact,
};
use anyhow::{Context, Result, anyhow, bail};
use flate2::read::GzDecoder;
use reqwest::blocking::Client;
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::time::Duration;
use tar::Archive;

pub const BUNDLE_SCHEMA_VERSION: u32 = 2;
pub const BUNDLE_VERSION: &str = "matching-bundle-v2";
pub const BUNDLE_KIND: &str = "askman.matching-bundle";
pub const MATCHING_DATABASE: &str = "matching.db";
pub const BUNDLE_MANIFEST: &str = "manifest.json";
pub const MODEL_DIRECTORY: &str = "model-cache";
pub const MODEL_REFERENCE: &str = "refs/main";
pub const REQUIRED_PLATFORMS: [&str; 4] = ["common", "linux", "osx", "windows"];

/// Release assets are deliberately fixed to the CLI's compatible release.
/// `setup` and `update` never consult a mutable `latest` endpoint.
pub const RELEASE_TAG: &str = concat!("v", env!("CARGO_PKG_VERSION"));
pub const RELEASE_BASE_URL: &str = "https://github.com/0bmario/askman/releases/download";
pub const RELEASE_MANIFEST_ASSET: &str = "matching-bundle-manifest.json";
pub const RELEASE_ARCHIVE_ASSET: &str = "matching-bundle.tar.gz";

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
    pub parser_version: String,
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
    parser_version: &'a str,
    cli_compatibility: &'a str,
    source: &'a SourceMetadata,
    platforms: &'a [String],
    platform_filtering: &'a str,
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
    crate::tldr_subset::validate_manifest(&source_manifest)
        .context("source manifest is not compatible with the bundle builder")?;
    let output = absolute_path(&options.output)?;
    if path_entry_exists(&output) {
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
    if path_entry_exists(&temporary) {
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
        parser_version: artifact_metadata_from_file(&dense_output, "parser_version")?,
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
    if !root.is_dir() {
        bail!("matching bundle is not a directory: {}", bundle.display());
    }
    let manifest_path = root.join(BUNDLE_MANIFEST);
    let manifest: BundleManifest =
        serde_json::from_slice(&fs::read(&manifest_path).with_context(|| {
            format!("failed to read bundle manifest {}", manifest_path.display())
        })?)
        .context("failed to parse matching bundle manifest")?;
    validate_bundle_manifest(&manifest)?;

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
    validate_bundle_file_inventory(&root, &manifest)?;
    Ok(manifest)
}

/// Validate the manifest identity and compatibility fields without reading its
/// component files. The complete directory validator below must still run
/// before activation.
pub fn validate_bundle_manifest(manifest: &BundleManifest) -> Result<()> {
    validate_manifest_shape(manifest)?;
    validate_bundle_id(&manifest.bundle_id)?;
    if manifest.bundle_id != bundle_id(manifest)? {
        bail!("matching bundle identity does not match its manifest");
    }
    Ok(())
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
    if manifest.parser_version != PARSER_VERSION {
        bail!("unsupported matching bundle parser version");
    }
    validate_cli_compatibility(&manifest.cli_compatibility)?;
    validate_source_metadata(&manifest.source)?;
    validate_index_component(&manifest.lexical_index, "lexical index")?;
    validate_index_component(&manifest.corpus, "corpus")?;
    validate_dense_component(&manifest.dense_index)?;
    validate_platform_selection(&manifest.platform_selection)?;
    validate_dense_model_metadata(manifest)?;
    if manifest.embedding_model.assets.len() != MODEL_FILES.len() + 1 {
        bail!("matching bundle embedding model asset inventory is incomplete");
    }
    Ok(())
}

fn validate_source_metadata(source: &SourceMetadata) -> Result<()> {
    if source.digest_algorithm != "sha256" {
        bail!("matching bundle source digest algorithm is incompatible");
    }
    validate_sha256(&source.digest).context("matching bundle source digest is invalid")?;
    for (name, value) in [
        ("source name", source.name.as_str()),
        ("source revision", source.revision.as_str()),
        ("source URL", source.url.as_str()),
        ("source attribution", source.attribution.as_str()),
        ("license name", source.license.name.as_str()),
        ("license URL", source.license.url.as_str()),
    ] {
        if value.is_empty() {
            bail!("matching bundle {name} is empty");
        }
    }
    Ok(())
}

fn validate_index_component(component: &IndexComponent, name: &str) -> Result<()> {
    if component.version.is_empty() {
        bail!("matching bundle {name} version is empty");
    }
    validate_relative_path(&component.path)?;
    if component.size_bytes == 0 {
        bail!("matching bundle {name} size is invalid");
    }
    validate_sha256(&component.sha256)
        .with_context(|| format!("matching bundle {name} digest is invalid"))
}

fn validate_dense_component(component: &DenseComponent) -> Result<()> {
    if component.version.is_empty() {
        bail!("matching bundle dense index version is empty");
    }
    if component.recipe.is_empty() {
        bail!("matching bundle dense index recipe is empty");
    }
    validate_relative_path(&component.path)?;
    if component.size_bytes == 0 {
        bail!("matching bundle dense index size is invalid");
    }
    validate_sha256(&component.sha256).context("matching bundle dense index digest is invalid")
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
        if asset.size_bytes == 0 {
            bail!("bundle model asset size is invalid: {}", asset.path);
        }
        validate_sha256(&asset.sha256)
            .with_context(|| format!("bundle model asset digest is invalid: {}", asset.path))?;
        let path = root.join(&asset.path);
        let canonical = fs::canonicalize(&path)
            .with_context(|| format!("bundle model asset is missing: {}", asset.path))?;
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

fn validate_bundle_file_inventory(root: &Path, manifest: &BundleManifest) -> Result<()> {
    let mut actual = HashSet::new();
    collect_bundle_files(root, root, &mut actual)?;

    let mut expected = HashSet::from([BUNDLE_MANIFEST.to_string()]);
    expected.insert(manifest.corpus.path.clone());
    expected.insert(manifest.lexical_index.path.clone());
    expected.insert(manifest.dense_index.path.clone());
    expected.extend(
        manifest
            .embedding_model
            .assets
            .iter()
            .map(|asset| asset.path.clone()),
    );

    if actual != expected {
        let missing = expected.difference(&actual).cloned().collect::<Vec<_>>();
        let unexpected = actual.difference(&expected).cloned().collect::<Vec<_>>();
        bail!(
            "matching bundle file inventory is incompatible; missing: {}; unexpected: {}",
            display_paths(&missing),
            display_paths(&unexpected)
        );
    }
    Ok(())
}

fn collect_bundle_files(root: &Path, directory: &Path, files: &mut HashSet<String>) -> Result<()> {
    let mut entries = fs::read_dir(directory)
        .with_context(|| {
            format!(
                "failed to enumerate bundle directory {}",
                directory.display()
            )
        })?
        .collect::<std::io::Result<Vec<_>>>()?;
    entries.sort_by_key(|entry| entry.file_name());

    for entry in entries {
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)?;
        if metadata.file_type().is_symlink() {
            bail!("matching bundle contains a symlink: {}", path.display());
        }
        if metadata.is_dir() {
            collect_bundle_files(root, &path, files)?;
        } else if metadata.is_file() {
            let relative = path
                .strip_prefix(root)
                .map_err(|_| anyhow!("bundle file is outside bundle root"))?
                .to_str()
                .ok_or_else(|| anyhow!("bundle file path is not UTF-8: {}", path.display()))?
                .replace('\\', "/");
            files.insert(relative);
        } else {
            bail!(
                "matching bundle contains a non-regular file: {}",
                path.display()
            );
        }
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

    if manifest.parser_version != artifact_metadata(connection, "parser_version")? {
        bail!("bundle parser version does not match the matching database");
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
        parser_version: &manifest.parser_version,
        cli_compatibility: &manifest.cli_compatibility,
        source: &manifest.source,
        platforms: &manifest.platform_selection.platforms,
        platform_filtering: &manifest.platform_selection.filtering,
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
    if path_entry_exists(output) {
        bail!(
            "refusing to replace existing matching bundle output {}; choose a new versioned output path",
            output.display()
        );
    }
    fs::rename(temporary, output)
        .with_context(|| format!("failed to publish matching bundle {}", output.display()))
}

/// Detect any existing directory entry, including a dangling symlink.
fn path_entry_exists(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok()
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

const ACTIVE_STATE_SCHEMA_VERSION: u32 = 1;
const ACTIVE_STATE_FILE: &str = "active-bundle.json";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ActiveBundleState {
    pub schema_version: u32,
    pub active_bundle_id: String,
    pub previous_bundle_id: Option<String>,
}

#[derive(Debug, Clone)]
pub struct BundleStore {
    root: PathBuf,
    active_state: PathBuf,
    release_base_url: String,
}

impl BundleStore {
    /// Open the lifecycle store below the supplied Askman data directory.
    /// Construction is read-only; setup/update create the store as needed.
    pub fn new(app_dir: &Path) -> Self {
        Self::with_release_base_url(app_dir, RELEASE_BASE_URL)
    }

    /// Construct a store against a release download root. This is useful for
    /// offline integration tests; the release tag and asset names remain
    /// fixed and are still checked by the downloader.
    pub fn with_release_base_url(app_dir: &Path, release_base_url: impl Into<String>) -> Self {
        Self {
            root: app_dir.join("bundles"),
            active_state: app_dir.join(ACTIVE_STATE_FILE),
            release_base_url: release_base_url.into(),
        }
    }

    /// Return and revalidate the active bundle. This path never performs I/O
    /// outside the local store and never creates or downloads anything.
    pub fn active_bundle(&self) -> Result<(PathBuf, BundleManifest)> {
        let state = self
            .read_state()?
            .ok_or_else(|| anyhow!("no active matching bundle; run `askman setup` first"))?;
        self.load_bundle(&state.active_bundle_id)
    }

    /// First-use setup. Existing valid setup is idempotent; an invalid active
    /// state is reported instead of being repaired or replaced implicitly.
    pub fn setup(&self) -> Result<BundleManifest> {
        if self.read_state()?.is_some() {
            return self.active_bundle().map(|(_, manifest)| manifest);
        }
        self.acquire_and_activate()
    }

    /// Explicitly acquire the release-pinned bundle and activate it after the
    /// same full directory validation used by setup and query.
    pub fn update(&self) -> Result<BundleManifest> {
        if let Some(state) = self.read_state()? {
            self.load_bundle(&state.active_bundle_id)?;
        }
        self.acquire_and_activate()
    }

    /// Atomically switch to the previous valid bundle. The current bundle is
    /// retained as the next rollback target.
    pub fn rollback(&self) -> Result<BundleManifest> {
        self.rollback_with(validate_matching_bundle)
    }

    fn rollback_with<F>(&self, validator: F) -> Result<BundleManifest>
    where
        F: Fn(&Path) -> Result<BundleManifest> + Copy,
    {
        let state = self
            .read_state()?
            .ok_or_else(|| anyhow!("no active matching bundle; nothing to roll back"))?;
        let previous = state
            .previous_bundle_id
            .as_deref()
            .ok_or_else(|| anyhow!("no previous valid matching bundle is available"))?;
        let (_, previous_manifest) =
            self.load_bundle_with(previous, validator)
                .with_context(|| {
                    format!(
                        "cannot roll back because previous matching bundle {previous} is invalid"
                    )
                })?;

        self.write_state_atomic(&ActiveBundleState {
            schema_version: ACTIVE_STATE_SCHEMA_VERSION,
            active_bundle_id: previous.to_string(),
            previous_bundle_id: Some(state.active_bundle_id),
        })?;
        Ok(previous_manifest)
    }

    /// Resolve the immutable on-disk path for a bundle ID. The path is not
    /// created or replaced by this method.
    pub fn bundle_path(&self, bundle_id: &str) -> Result<PathBuf> {
        validate_bundle_id(bundle_id)?;
        Ok(self.root.join(storage_name(bundle_id)))
    }

    fn acquire_and_activate(&self) -> Result<BundleManifest> {
        self.ensure_store_root()?;
        let (bundle_path, manifest, newly_published) = self.acquire_release_bundle()?;
        if let Err(error) = self.activate_manifest(&manifest) {
            if newly_published {
                fs::remove_dir_all(&bundle_path).with_context(|| {
                    format!(
                        "activation failed and newly published matching bundle {} could not be removed",
                        manifest.bundle_id
                    )
                })?;
            }
            return Err(error);
        }
        debug_assert!(bundle_path.is_dir());
        Ok(manifest)
    }

    fn acquire_release_bundle(&self) -> Result<(PathBuf, BundleManifest, bool)> {
        let staging = self.create_staging_directory()?;
        let archive = self.temporary_archive_path()?;
        let result = (|| -> Result<(PathBuf, BundleManifest, bool)> {
            let manifest_bytes = self.download_asset(RELEASE_MANIFEST_ASSET, None)?;
            let manifest: BundleManifest = serde_json::from_slice(&manifest_bytes)
                .context("release matching-bundle manifest is not valid JSON")?;
            validate_release_manifest(&manifest)?;

            self.download_asset(RELEASE_ARCHIVE_ASSET, Some(&archive))?;
            extract_bundle_archive(&archive, &staging)?;
            let embedded = validate_matching_bundle(&staging)
                .context("downloaded matching bundle failed validation")?;
            if embedded != manifest {
                bail!("release matching-bundle manifest does not match the bundle archive");
            }

            let (destination, newly_published) =
                self.publish_validated_bundle(&staging, &manifest)?;
            Ok((destination, manifest, newly_published))
        })();

        let _ = fs::remove_file(&archive);
        let _ = fs::remove_dir_all(&staging);
        result
    }

    fn download_asset(&self, asset: &str, destination: Option<&Path>) -> Result<Vec<u8>> {
        let url = release_asset_url(&self.release_base_url, asset)?;
        let client = Client::builder()
            .timeout(Duration::from_secs(120))
            .user_agent(format!("askman/{}", env!("CARGO_PKG_VERSION")))
            .build()
            .context("failed to create release download client")?;
        let mut response = client
            .get(&url)
            .send()
            .with_context(|| format!("failed to download release asset {url}"))?
            .error_for_status()
            .with_context(|| format!("release asset is unavailable: {url}"))?;

        if let Some(destination) = destination {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(destination)
                .with_context(|| {
                    format!(
                        "failed to create temporary release asset {}",
                        destination.display()
                    )
                })?;
            response.copy_to(&mut file)?;
            file.sync_all()?;
            Ok(Vec::new())
        } else {
            let mut bytes = Vec::new();
            response.read_to_end(&mut bytes)?;
            Ok(bytes)
        }
    }

    fn publish_validated_bundle(
        &self,
        staging: &Path,
        manifest: &BundleManifest,
    ) -> Result<(PathBuf, bool)> {
        self.publish_validated_bundle_checked(staging, manifest, validate_matching_bundle)
    }

    #[cfg(test)]
    fn publish_validated_bundle_with<F>(
        &self,
        staging: &Path,
        manifest: &BundleManifest,
        validator: F,
    ) -> Result<PathBuf>
    where
        F: Fn(&Path) -> Result<BundleManifest> + Copy,
    {
        Ok(self
            .publish_validated_bundle_checked(staging, manifest, validator)?
            .0)
    }

    fn publish_validated_bundle_checked<F>(
        &self,
        staging: &Path,
        manifest: &BundleManifest,
        validator: F,
    ) -> Result<(PathBuf, bool)>
    where
        F: Fn(&Path) -> Result<BundleManifest> + Copy,
    {
        let validated = validator(staging)
            .context("matching bundle failed validation before immutable publication")?;
        if validated != *manifest {
            bail!("matching bundle manifest changed during validation");
        }
        let destination = self.bundle_path(&manifest.bundle_id)?;
        if path_entry_exists(&destination) {
            let existing = self
                .load_bundle_with(&manifest.bundle_id, validator)
                .with_context(|| {
                format!(
                    "immutable bundle ID {} already exists but is invalid; refusing to replace it",
                    manifest.bundle_id
                )
            })?;
            if existing.1 != *manifest {
                bail!(
                    "immutable bundle ID {} is already stored with different manifest metadata",
                    manifest.bundle_id
                );
            }
            return Ok((existing.0, false));
        }

        atomic_replace(staging, &destination).with_context(|| {
            format!(
                "failed to publish validated matching bundle {}",
                manifest.bundle_id
            )
        })?;
        Ok((destination, true))
    }

    fn activate_manifest(&self, manifest: &BundleManifest) -> Result<()> {
        let state = self.read_state()?;
        if state
            .as_ref()
            .is_some_and(|state| state.active_bundle_id == manifest.bundle_id)
        {
            return Ok(());
        }
        self.write_state_atomic(&ActiveBundleState {
            schema_version: ACTIVE_STATE_SCHEMA_VERSION,
            active_bundle_id: manifest.bundle_id.clone(),
            previous_bundle_id: state.map(|state| state.active_bundle_id),
        })
    }

    fn load_bundle(&self, bundle_id: &str) -> Result<(PathBuf, BundleManifest)> {
        self.load_bundle_with(bundle_id, validate_matching_bundle)
    }

    fn load_bundle_with<F>(
        &self,
        bundle_id: &str,
        validator: F,
    ) -> Result<(PathBuf, BundleManifest)>
    where
        F: Fn(&Path) -> Result<BundleManifest>,
    {
        self.validate_store_root()?;
        let path = self.bundle_path(bundle_id)?;
        if !path_entry_exists(&path) {
            bail!("matching bundle {bundle_id} is missing from local storage");
        }
        let metadata = fs::symlink_metadata(&path)?;
        if metadata.file_type().is_symlink() {
            bail!("matching bundle {bundle_id} is a symlink, not an immutable bundle directory");
        }
        if !metadata.is_dir() {
            bail!("matching bundle {bundle_id} is not a directory");
        }
        let manifest = validator(&path)
            .with_context(|| format!("matching bundle {bundle_id} failed validation"))?;
        if manifest.bundle_id != bundle_id {
            bail!("stored matching bundle ID does not match its directory identity");
        }
        Ok((path, manifest))
    }

    fn ensure_store_root(&self) -> Result<()> {
        if path_entry_exists(&self.root) {
            let metadata = fs::symlink_metadata(&self.root)?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                bail!(
                    "matching bundle storage is not a regular directory: {}",
                    self.root.display()
                );
            }
        } else {
            fs::create_dir_all(&self.root).with_context(|| {
                format!(
                    "failed to create matching bundle storage {}",
                    self.root.display()
                )
            })?;
        }
        Ok(())
    }

    fn validate_store_root(&self) -> Result<()> {
        if !path_entry_exists(&self.root) {
            bail!("matching bundle storage is missing; run `askman setup` first");
        }
        let metadata = fs::symlink_metadata(&self.root)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            bail!(
                "matching bundle storage is not a regular directory: {}",
                self.root.display()
            );
        }
        Ok(())
    }

    fn create_staging_directory(&self) -> Result<PathBuf> {
        let path = self.root.join(format!(".bundle-{}.part", unique_suffix()));
        fs::create_dir(&path).with_context(|| {
            format!(
                "failed to create temporary matching bundle directory {}",
                path.display()
            )
        })?;
        Ok(path)
    }

    fn temporary_archive_path(&self) -> Result<PathBuf> {
        let path = self
            .root
            .join(format!(".download-{}.tar.gz", unique_suffix()));
        let _ = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .with_context(|| format!("failed to reserve temporary archive {}", path.display()))?;
        let _ = fs::remove_file(&path);
        Ok(path)
    }

    fn read_state(&self) -> Result<Option<ActiveBundleState>> {
        if !path_entry_exists(&self.active_state) {
            return Ok(None);
        }
        let metadata = fs::symlink_metadata(&self.active_state)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            bail!("active matching bundle state is not a regular file");
        }
        let contents = fs::read_to_string(&self.active_state)
            .with_context(|| format!("failed to read {}", self.active_state.display()))?;
        let nonempty_lines = contents
            .lines()
            .filter(|line| !line.trim().is_empty())
            .collect::<Vec<_>>();
        let mut latest = None;
        for (index, line) in nonempty_lines.iter().enumerate() {
            match serde_json::from_str::<ActiveBundleState>(line) {
                Ok(state) => {
                    validate_state(&state)?;
                    latest = Some(state);
                }
                Err(error)
                    if index + 1 == nonempty_lines.len() && !line.trim_end().ends_with('}') =>
                {
                    // A process interrupted during one append leaves an
                    // incomplete final record. The previous complete record
                    // remains the active state.
                    let _ = error;
                }
                Err(error) => {
                    return Err(error).context("active matching bundle state is not valid JSON");
                }
            }
        }
        Ok(latest)
    }

    fn write_state_atomic(&self, state: &ActiveBundleState) -> Result<()> {
        validate_state(state)?;
        self.ensure_store_root()?;
        if path_entry_exists(&self.active_state) {
            let metadata = fs::symlink_metadata(&self.active_state)?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                bail!("active matching bundle state is not a replaceable regular file");
            }
        }

        let temporary = self
            .active_state
            .with_file_name(format!(".active-bundle-{}.part", unique_suffix()));
        let result = (|| -> Result<()> {
            let mut file = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&temporary)
                .with_context(|| {
                    format!(
                        "failed to create temporary active bundle state {}",
                        temporary.display()
                    )
                })?;
            let mut bytes = serde_json::to_vec(state)?;
            bytes.push(b'\n');
            file.write_all(&bytes)?;
            file.sync_all()?;
            atomic_replace(&temporary, &self.active_state)?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        result
    }
}

fn validate_release_manifest(manifest: &BundleManifest) -> Result<()> {
    validate_bundle_manifest(manifest)?;
    let expected_cli = format!("askman={}", env!("CARGO_PKG_VERSION"));
    if manifest.cli_compatibility != expected_cli {
        bail!(
            "release matching bundle is incompatible with this CLI: declared {}, expected {}",
            manifest.cli_compatibility,
            expected_cli
        );
    }
    Ok(())
}

fn validate_state(state: &ActiveBundleState) -> Result<()> {
    if state.schema_version != ACTIVE_STATE_SCHEMA_VERSION {
        bail!("unsupported active matching bundle state version");
    }
    validate_bundle_id(&state.active_bundle_id)?;
    if state
        .previous_bundle_id
        .as_ref()
        .is_some_and(|previous| previous == &state.active_bundle_id)
    {
        bail!("active matching bundle state repeats the active bundle ID");
    }
    if let Some(previous) = &state.previous_bundle_id {
        validate_bundle_id(previous)?;
    }
    Ok(())
}

fn validate_bundle_id(bundle_id: &str) -> Result<()> {
    if !bundle_id.starts_with(&format!("{BUNDLE_VERSION}:"))
        || bundle_id
            .chars()
            .any(|character| character == '/' || character == '\\' || character.is_control())
    {
        bail!("matching bundle ID is invalid: {bundle_id}");
    }
    Ok(())
}

fn storage_name(bundle_id: &str) -> String {
    let mut name = String::new();
    for byte in bundle_id.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'.' | b'-' | b'_' => name.push(byte as char),
            _ => name.push_str(&format!("%{byte:02x}")),
        }
    }
    name
}

fn release_asset_url(base_url: &str, asset: &str) -> Result<String> {
    if asset != RELEASE_MANIFEST_ASSET && asset != RELEASE_ARCHIVE_ASSET {
        bail!("unsupported release asset: {asset}");
    }
    if base_url.is_empty() || base_url.chars().any(char::is_whitespace) {
        bail!("release base URL is invalid");
    }
    Ok(format!(
        "{}/{}/{}",
        base_url.trim_end_matches('/'),
        RELEASE_TAG,
        asset
    ))
}

fn extract_bundle_archive(archive_path: &Path, destination: &Path) -> Result<()> {
    let archive = File::open(archive_path).with_context(|| {
        format!(
            "failed to open downloaded bundle archive {}",
            archive_path.display()
        )
    })?;
    let decoder = GzDecoder::new(archive);
    let mut archive = Archive::new(decoder);
    let entries = archive
        .entries()
        .context("failed to read matching bundle archive")?;
    for entry in entries {
        let mut entry = entry.context("failed to read matching bundle archive entry")?;
        let relative = entry
            .path()
            .context("matching bundle archive entry has no path")?
            .into_owned();
        let relative_text = relative
            .to_str()
            .ok_or_else(|| anyhow!("matching bundle archive entry path is not UTF-8"))?;
        validate_relative_path(relative_text)?;
        let output = destination.join(&relative);
        ensure_no_symlink_parents(destination, &output)?;
        if path_entry_exists(&output) {
            bail!("matching bundle archive contains a duplicate path: {relative_text}");
        }

        if entry.header().entry_type().is_dir() {
            fs::create_dir_all(&output)?;
        } else if entry.header().entry_type().is_file() {
            if let Some(parent) = output.parent() {
                fs::create_dir_all(parent)?;
            }
            entry.unpack(&output).with_context(|| {
                format!("failed to extract matching bundle file {relative_text}")
            })?;
        } else {
            bail!("matching bundle archive contains unsupported entry: {relative_text}");
        }
    }
    Ok(())
}

fn ensure_no_symlink_parents(root: &Path, path: &Path) -> Result<()> {
    let relative = path
        .strip_prefix(root)
        .map_err(|_| anyhow!("archive output escaped staging directory"))?;
    let mut current = root.to_path_buf();
    for component in relative.components() {
        current.push(component.as_os_str());
        if current == path {
            break;
        }
        if path_entry_exists(&current) {
            let metadata = fs::symlink_metadata(&current)?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                bail!("matching bundle archive path crosses a non-directory entry");
            }
        }
    }
    Ok(())
}

fn unique_suffix() -> String {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    format!("{}-{nanos}", std::process::id())
}

#[cfg(not(windows))]
fn atomic_replace(source: &Path, destination: &Path) -> std::io::Result<()> {
    fs::rename(source, destination)
}

#[cfg(windows)]
fn atomic_replace(source: &Path, destination: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH, MoveFileExW,
    };

    let source = source
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let destination = destination
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let flags = MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH;
    if unsafe { MoveFileExW(source.as_ptr(), destination.as_ptr(), flags) } == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_manifest(parser_version: &str) -> BundleManifest {
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
            version: "fts5-unicode61-v1".to_string(),
            path: MATCHING_DATABASE.to_string(),
            size_bytes: 10,
            sha256: "b".repeat(64),
        };
        BundleManifest {
            schema_version: BUNDLE_SCHEMA_VERSION,
            bundle_id: String::new(),
            bundle_version: BUNDLE_VERSION.to_string(),
            artifact_kind: BUNDLE_KIND.to_string(),
            parser_version: parser_version.to_string(),
            source,
            platform_selection: PlatformSelection {
                platforms: REQUIRED_PLATFORMS
                    .iter()
                    .map(|value| value.to_string())
                    .collect(),
                filtering: "query-time".to_string(),
            },
            lexical_index: component,
            dense_index: DenseComponent {
                version: DENSE_INDEX_VERSION.to_string(),
                recipe: "description".to_string(),
                path: MATCHING_DATABASE.to_string(),
                size_bytes: 10,
                sha256: "b".repeat(64),
            },
            corpus: IndexComponent {
                version: format!("{parser_version}-corpus-v1"),
                path: MATCHING_DATABASE.to_string(),
                size_bytes: 10,
                sha256: "b".repeat(64),
            },
            embedding_model: EmbeddingModel {
                id: MODEL_ID.to_string(),
                revision: MODEL_REVISION.to_string(),
                runtime: MODEL_RUNTIME.to_string(),
                dimension: MODEL_DIMENSION,
                max_length: MODEL_MAX_LENGTH,
                assets: Vec::new(),
            },
            cli_compatibility: "askman=0.3.3".to_string(),
        }
    }

    #[test]
    fn bundle_identity_is_stable_for_unchanged_inputs() {
        let manifest = test_manifest(PARSER_VERSION);
        let first = bundle_id(&manifest).unwrap();
        let second = bundle_id(&manifest.clone()).unwrap();
        assert_eq!(first, second);

        let mut changed_compatibility = manifest;
        changed_compatibility.cli_compatibility = "askman=0.3.4".to_string();
        assert_ne!(first, bundle_id(&changed_compatibility).unwrap());

        let mut changed_filtering = changed_compatibility.clone();
        changed_filtering.platform_selection.filtering = "build-time".to_string();
        assert_ne!(
            bundle_id(&changed_compatibility).unwrap(),
            bundle_id(&changed_filtering).unwrap()
        );

        let mut changed_parser = changed_compatibility;
        changed_parser.parser_version = "tldr-subset-v4".to_string();
        assert_ne!(first, bundle_id(&changed_parser).unwrap());
    }

    #[test]
    fn parser_version_must_match_manifest_and_database() {
        let mut manifest = test_manifest(PARSER_VERSION);
        manifest.parser_version = "tldr-subset-v4".to_string();
        let error = validate_manifest_shape(&manifest).unwrap_err().to_string();
        assert!(error.contains("unsupported matching bundle parser version"));

        let connection = Connection::open_in_memory().unwrap();
        connection
            .execute_batch(
                "CREATE TABLE artifact_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                 INSERT INTO artifact_metadata VALUES
                   ('lexical_index_tokenizer', 'unicode61'),
                   ('parser_version', 'tldr-subset-v3'),
                   ('dense_embedding_text_recipe', 'description');",
            )
            .unwrap();
        let mut manifest = test_manifest(PARSER_VERSION);
        validate_database_component_versions(&manifest, &connection).unwrap();

        manifest.parser_version = "tldr-subset-v4".to_string();
        let error = validate_database_component_versions(&manifest, &connection)
            .unwrap_err()
            .to_string();
        assert!(error.contains("bundle parser version does not match"));
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

    #[cfg(unix)]
    #[test]
    fn dangling_bundle_output_is_refused_without_replacing_the_link() {
        use std::os::unix::fs::symlink;

        let directory = tempfile::tempdir().unwrap();
        let output = directory.path().join("matching-bundle");
        symlink("missing-target", &output).unwrap();

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
        assert!(
            fs::symlink_metadata(output)
                .unwrap()
                .file_type()
                .is_symlink()
        );
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

    fn lifecycle_manifest(revision: &str) -> BundleManifest {
        let mut manifest = test_manifest(PARSER_VERSION);
        manifest.source.revision = revision.to_string();
        manifest.bundle_id = bundle_id(&manifest).unwrap();
        manifest
    }

    fn test_bundle_validator(path: &Path) -> Result<BundleManifest> {
        Ok(serde_json::from_slice(&fs::read(
            path.join(BUNDLE_MANIFEST),
        )?)?)
    }

    fn install_test_bundle(
        store: &BundleStore,
        manifest: &BundleManifest,
        activate: bool,
    ) -> PathBuf {
        store.ensure_store_root().unwrap();
        let staging = store.create_staging_directory().unwrap();
        fs::write(
            staging.join(BUNDLE_MANIFEST),
            serde_json::to_vec(manifest).unwrap(),
        )
        .unwrap();
        let destination = store
            .publish_validated_bundle_with(&staging, manifest, test_bundle_validator)
            .unwrap();
        if activate {
            store.activate_manifest(manifest).unwrap();
        }
        destination
    }

    #[test]
    fn first_use_setup_state_has_one_active_immutable_bundle() {
        let directory = tempfile::tempdir().unwrap();
        let store = BundleStore::new(directory.path());
        let error = store.active_bundle().unwrap_err().to_string();
        assert!(error.contains("run `askman setup` first"));

        let manifest = lifecycle_manifest("first-use");
        let bundle_path = install_test_bundle(&store, &manifest, true);
        let state = store.read_state().unwrap().unwrap();
        assert_eq!(state.active_bundle_id, manifest.bundle_id);
        assert_eq!(state.previous_bundle_id, None);
        assert!(bundle_path.is_dir());
        assert_eq!(store.bundle_path(&manifest.bundle_id).unwrap(), bundle_path);
    }

    #[test]
    fn successful_update_preserves_previous_bundle_for_rollback() {
        let directory = tempfile::tempdir().unwrap();
        let store = BundleStore::new(directory.path());
        let first = lifecycle_manifest("first");
        let second = lifecycle_manifest("second");
        let first_path = install_test_bundle(&store, &first, true);
        let second_path = install_test_bundle(&store, &second, true);

        let updated = store.read_state().unwrap().unwrap();
        assert_eq!(updated.active_bundle_id, second.bundle_id);
        assert_eq!(updated.previous_bundle_id, Some(first.bundle_id.clone()));
        assert!(first_path.is_dir());
        assert!(second_path.is_dir());

        let rolled_back = store.rollback_with(test_bundle_validator).unwrap();
        assert_eq!(rolled_back.bundle_id, first.bundle_id);
        let rolled_state = store.read_state().unwrap().unwrap();
        assert_eq!(rolled_state.active_bundle_id, first.bundle_id);
        assert_eq!(rolled_state.previous_bundle_id, Some(second.bundle_id));
        assert!(first_path.is_dir());
        assert!(second_path.is_dir());
    }

    #[test]
    fn interrupted_active_state_is_replaced_before_next_activation() {
        let directory = tempfile::tempdir().unwrap();
        let store = BundleStore::new(directory.path());
        let first = lifecycle_manifest("first");
        let second = lifecycle_manifest("second");
        install_test_bundle(&store, &first, true);

        let mut state = OpenOptions::new()
            .append(true)
            .open(&store.active_state)
            .unwrap();
        state.write_all(br#"{"#).unwrap();
        state.sync_all().unwrap();

        install_test_bundle(&store, &second, true);

        let contents = fs::read_to_string(&store.active_state).unwrap();
        assert_eq!(contents.lines().count(), 1);
        assert_eq!(
            store.read_state().unwrap().unwrap().active_bundle_id,
            second.bundle_id
        );
    }

    #[test]
    fn failed_candidate_validation_preserves_active_state_and_assets() {
        let directory = tempfile::tempdir().unwrap();
        let store = BundleStore::new(directory.path());
        let first = lifecycle_manifest("first");
        let second = lifecycle_manifest("second");
        install_test_bundle(&store, &first, true);
        let second_path = install_test_bundle(&store, &second, true);
        let before = store.read_state().unwrap().unwrap();

        let failed = lifecycle_manifest("failed");
        let staging = store.create_staging_directory().unwrap();
        fs::write(
            staging.join(BUNDLE_MANIFEST),
            serde_json::to_vec(&failed).unwrap(),
        )
        .unwrap();
        let error = store
            .publish_validated_bundle_with(&staging, &failed, |_path| {
                bail!("bundle component digest mismatch: matching.db")
            })
            .unwrap_err()
            .to_string();
        assert!(error.contains("failed validation"));
        assert_eq!(store.read_state().unwrap().unwrap(), before);
        assert!(second_path.is_dir());
        assert!(!store.bundle_path(&failed.bundle_id).unwrap().exists());
        fs::remove_dir_all(staging).unwrap();
    }

    #[test]
    fn immutable_bundle_id_never_replaces_existing_directory() {
        let directory = tempfile::tempdir().unwrap();
        let store = BundleStore::new(directory.path());
        let original = lifecycle_manifest("original");
        let original_path = install_test_bundle(&store, &original, true);
        let marker = original_path.join("marker");
        fs::write(&marker, b"original").unwrap();

        let mut replacement = lifecycle_manifest("replacement");
        replacement.bundle_id = original.bundle_id.clone();
        let staging = store.create_staging_directory().unwrap();
        fs::write(
            staging.join(BUNDLE_MANIFEST),
            serde_json::to_vec(&replacement).unwrap(),
        )
        .unwrap();
        let error = store
            .publish_validated_bundle_with(&staging, &replacement, test_bundle_validator)
            .unwrap_err()
            .to_string();
        assert!(error.contains("already stored with different manifest metadata"));
        assert_eq!(fs::read(marker).unwrap(), b"original");
        fs::remove_dir_all(staging).unwrap();
    }

    #[test]
    fn archive_extraction_rejects_path_traversal() {
        use flate2::{Compression, write::GzEncoder};

        let directory = tempfile::tempdir().unwrap();
        let archive_path = directory.path().join("bundle.tar.gz");
        let file = File::create(&archive_path).unwrap();
        let encoder = GzEncoder::new(file, Compression::default());
        let mut builder = tar::Builder::new(encoder);
        let bytes = b"not allowed";
        let mut header = tar::Header::new_gnu();
        header.set_size(bytes.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        let name = b"../outside.txt";
        header.as_mut_bytes()[..name.len()].copy_from_slice(name);
        header.set_cksum();
        builder.append(&header, &bytes[..]).unwrap();
        builder
            .into_inner()
            .unwrap()
            .finish()
            .unwrap()
            .sync_all()
            .unwrap();

        let destination = directory.path().join("staging");
        fs::create_dir(&destination).unwrap();
        let error = extract_bundle_archive(&archive_path, &destination)
            .unwrap_err()
            .to_string();
        assert!(error.contains("safe relative path"));
        assert!(!directory.path().join("outside.txt").exists());
    }

    #[test]
    fn active_bundle_lookup_does_not_contact_release_base_url() {
        use std::net::TcpListener;

        let directory = tempfile::tempdir().unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let address = listener.local_addr().unwrap();
        let store =
            BundleStore::with_release_base_url(directory.path(), format!("http://{address}"));

        let error = store.active_bundle().unwrap_err().to_string();
        assert!(error.contains("run `askman setup` first"));
        assert!(
            matches!(listener.accept(), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock)
        );
    }
}
