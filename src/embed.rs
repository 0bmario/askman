use anyhow::{Context, Result};
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use std::path::Path;

pub fn init_model(app_dir: &Path) -> Result<TextEmbedding> {
    let cache_dir = app_dir.join("models");
    // The int8 query encoder matches the fp32 vectors in the commands database (built by
    // import_tldr with AllMiniLML6V2) on the eval set, at a quarter of the download.
    let embed_options = InitOptions::new(EmbeddingModel::AllMiniLML6V2Q)
        .with_show_download_progress(true)
        .with_cache_dir(cache_dir.clone());
    TextEmbedding::try_new(embed_options).with_context(|| {
        format!(
            "failed to initialize embedding model AllMiniLML6V2Q with cache_dir {}",
            cache_dir.display()
        )
    })
}

pub fn embed_query(embedder: &TextEmbedding, query: &str) -> Result<Vec<f32>> {
    let q_vec = embedder.embed(vec![query], None)?[0].clone();
    Ok(q_vec)
}
