//! Scratch (not committed): time model init + one query embed for a fastembed model.
//! Usage: init_time <EmbeddingModel name> <cache_dir> <runs>
use fastembed::{EmbeddingModel, TextEmbedding, TextInitOptions};
use std::time::Instant;
fn main() -> anyhow::Result<()> {
    let a: Vec<String> = std::env::args().collect();
    let model: EmbeddingModel = a[1].parse().map_err(anyhow::Error::msg)?;
    let runs: usize = a[3].parse()?;
    for _ in 0..runs {
        let t = Instant::now();
        let mut m = TextEmbedding::try_new(TextInitOptions::new(model.clone()).with_cache_dir(a[2].clone().into()))?;
        let init = t.elapsed().as_secs_f64() * 1000.0;
        let t = Instant::now();
        m.embed(["copy files to a remote server"], None)?;
        println!("{:.2}\t{:.2}", init, t.elapsed().as_secs_f64() * 1000.0);
    }
    Ok(())
}
