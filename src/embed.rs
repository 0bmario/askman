use anyhow::Result;
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use std::path::Path;

pub fn init_model(app_dir: &Path) -> Result<TextEmbedding> {
    let embed_options = InitOptions::new(EmbeddingModel::AllMiniLML6V2)
        .with_show_download_progress(true)
        .with_cache_dir(app_dir.join("models"));
    Ok(TextEmbedding::try_new(embed_options)?)
}

pub fn embed_query(embedder: &TextEmbedding, query: &str) -> Result<Vec<f32>> {
    let q_vec = embedder.embed(vec![query], None)?[0].clone();
    Ok(q_vec)
}
