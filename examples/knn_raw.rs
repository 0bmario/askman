//! Diagnostic: the raw sqlite-vec KNN behind `rank`, before the distance cut-off,
//! `adjust_score` and the media gate. Reads `target_os<TAB>query` lines on stdin and
//! prints the 7 nearest rows per query as `command|os|raw_distance` cells.
//!
//! Usage: knn_raw <EmbeddingModel> <prefix|noprefix> <commands.db> <model cache dir>
use anyhow::{Result, bail};
use askman::{db, search};
use fastembed::{AutoDevicePolicy, EmbeddingModel, TextEmbedding, TextInitOptions};
use rusqlite::{Connection, params};
use std::io::BufRead;
use zerocopy::IntoBytes;

const ARCTIC_QUERY_PREFIX: &str = "Represent this sentence for searching relevant passages: ";

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let [_, model_name, prefix_mode, db_path, cache_dir] = args.as_slice() else {
        bail!("usage: knn_raw <EmbeddingModel> <prefix|noprefix> <commands.db> <model cache dir>");
    };
    let prefix = match prefix_mode.as_str() {
        "prefix" => ARCTIC_QUERY_PREFIX,
        "noprefix" => "",
        _ => bail!("expected prefix or noprefix, got {prefix_mode}"),
    };
    db::register_sqlite_vec();
    let model_kind: EmbeddingModel = model_name.parse().map_err(anyhow::Error::msg)?;
    let mut model = TextEmbedding::try_new(
        TextInitOptions::new(model_kind)
            .with_auto_device(AutoDevicePolicy::PreferCPU)
            .with_cache_dir(cache_dir.into()),
    )?;
    let conn = Connection::open(db_path)?;
    let mut stmt = conn.prepare(
        "SELECT command, os, distance FROM pages_vec
         WHERE (os = 'common' OR os = ?2) AND embedding MATCH ?1
         ORDER BY distance LIMIT 7",
    )?;
    for line in std::io::stdin().lock().lines() {
        let line = line?;
        let (os, query) = line
            .split_once('\t')
            .ok_or_else(|| anyhow::anyhow!("expected `os<TAB>query`, got {line:?}"))?;
        let target_os = search::get_target_os(os == "linux", os == "osx", os == "windows");
        let vector = model.embed(vec![format!("{prefix}{query}")], None)?.remove(0);
        let cells = stmt
            .query_map(params![vector.as_bytes(), target_os.as_str()], |row| {
                Ok(format!(
                    "{}|{}|{:.4}",
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, f64>(2)?
                ))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        println!("{}", cells.join("\t"));
    }
    Ok(())
}
