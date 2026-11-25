use anyhow::{Context, Result};
use fastembed::{AutoDevicePolicy, EmbeddingModel, TextEmbedding, TextInitOptions};
use std::path::Path;

/// snowflake-arctic-embed expects this prefix on queries (not on documents) for
/// retrieval; fastembed does not add it.
const QUERY_PREFIX: &str = "Represent this sentence for searching relevant passages: ";

pub fn init_model(app_dir: &Path) -> Result<TextEmbedding> {
    let cache_dir = app_dir.join("models");
    // The int8 query encoder is paired with the fp32 SnowflakeArcticEmbedXS
    // vectors in commands.db, at a quarter of the fp32 download.
    let embed_options = TextInitOptions::new(EmbeddingModel::SnowflakeArcticEmbedXSQ)
        // ort's default on macOS registers CoreML, which recompiles the model in
        // every process (~350 ms per query); fastembed 4.8 ran on the CPU.
        .with_auto_device(AutoDevicePolicy::PreferCPU)
        .with_show_download_progress(true)
        .with_cache_dir(cache_dir.clone());
    TextEmbedding::try_new(embed_options).with_context(|| {
        format!(
            "failed to initialize embedding model SnowflakeArcticEmbedXSQ with cache_dir {}",
            cache_dir.display()
        )
    })
}

pub fn embed_query(embedder: &mut TextEmbedding, query: &str) -> Result<Vec<f32>> {
    let q_vec = embedder.embed(vec![format!("{QUERY_PREFIX}{query}")], None)?[0].clone();
    Ok(q_vec)
}
