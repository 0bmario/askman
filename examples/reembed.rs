//! Rebuilds a commands.db with new vectors for the same rows, so an embedding
//! model change is measured without the data change a fresh tldr import brings.
//! The embedded text is rebuilt from the stored columns exactly as
//! `import_tldr` builds it.
//!
//! Usage:
//!   reembed <EmbeddingModel> <source.db> <target.db>   write a re-embedded copy
//!   reembed <EmbeddingModel> <source.db> --verify <n>  compare every n-th row's
//!                                                      new vector with the stored one
use anyhow::{Context, Result, bail};
use askman::db;
use fastembed::{AutoDevicePolicy, EmbeddingModel, TextEmbedding, TextInitOptions};
use rusqlite::{Connection, params};
use zerocopy::IntoBytes;

struct Row {
    rowid: i64,
    command: String,
    os: String,
    description: String,
    example_desc: String,
    example_cmd: String,
    embedding: Vec<u8>,
}

impl Row {
    /// Same format as `process_directory` in `src/import_tldr.rs`.
    fn embedding_text(&self) -> String {
        format!(
            "Task: {}. Command: {}. Description: {}. Example: {} {}",
            self.example_desc, self.command, self.description, self.example_desc, self.example_cmd
        )
    }
}

/// import_tldr embedded one text per call. Larger batches pad every text to the
/// longest one and drove the ONNX runtime past 30 GB of memory.
const ONE_TEXT_PER_CALL: usize = 1;

fn read_rows(source: &Connection) -> Result<Vec<Row>> {
    let mut stmt = source.prepare(
        "SELECT rowid, command, os, description, example_desc, example_cmd, embedding
         FROM pages_vec ORDER BY rowid",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok(Row {
            rowid: r.get(0)?,
            command: r.get(1)?,
            os: r.get(2)?,
            description: r.get(3)?,
            example_desc: r.get(4)?,
            example_cmd: r.get(5)?,
            embedding: r.get(6)?,
        })
    })?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

fn cosine(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let norm = |v: &[f32]| v.iter().map(|x| x * x).sum::<f32>().sqrt();
    dot / (norm(a) * norm(b))
}

fn verify(model: &mut TextEmbedding, rows: &[Row], every: usize) -> Result<()> {
    let sample: Vec<&Row> = rows.iter().step_by(every).collect();
    let texts: Vec<String> = sample.iter().map(|r| r.embedding_text()).collect();
    let mut max_difference = 0f32;
    for (row, vector) in sample.iter().zip(model.embed(&texts, Some(ONE_TEXT_PER_CALL))?) {
        let stored: Vec<f32> = row
            .embedding
            .chunks_exact(4)
            .map(|b| f32::from_le_bytes(b.try_into().unwrap()))
            .collect();
        max_difference = max_difference.max(1.0 - cosine(&stored, &vector));
    }
    println!("rows compared: {}, max cosine difference: {max_difference:e}", sample.len());
    Ok(())
}

fn write_copy(model: &mut TextEmbedding, rows: &[Row], target_path: &str) -> Result<()> {
    if std::path::Path::new(target_path).exists() {
        bail!("{target_path} exists; refusing to overwrite");
    }
    let mut target = Connection::open(target_path)?;
    target.execute(
        "CREATE VIRTUAL TABLE pages_vec USING vec0(
            command TEXT,
            os TEXT,
            description TEXT,
            example_desc TEXT,
            example_cmd TEXT,
            embedding FLOAT[384]
        )",
        [],
    )?;
    let transaction = target.transaction()?;
    for batch in rows.chunks(256) {
        let texts: Vec<String> = batch.iter().map(|r| r.embedding_text()).collect();
        for (row, vector) in batch.iter().zip(model.embed(&texts, Some(ONE_TEXT_PER_CALL))?) {
            transaction.execute(
                "INSERT INTO pages_vec(rowid, command, os, description, example_desc, example_cmd, embedding)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    row.rowid,
                    row.command,
                    row.os,
                    row.description,
                    row.example_desc,
                    row.example_cmd,
                    vector.as_bytes()
                ],
            )?;
        }
    }
    transaction.commit()?;
    target.execute_batch("VACUUM")?;
    println!("wrote {} rows to {target_path}", rows.len());
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let [_, model_name, source_path, rest @ ..] = args.as_slice() else {
        bail!("usage: reembed <EmbeddingModel> <source.db> (<target.db> | --verify <n>)");
    };
    db::register_sqlite_vec();
    let model_kind: EmbeddingModel = model_name.parse().map_err(anyhow::Error::msg)?;
    let mut model = TextEmbedding::try_new(TextInitOptions::new(model_kind).with_auto_device(AutoDevicePolicy::PreferCPU))
        .with_context(|| format!("failed to load {model_name}"))?;
    let rows = read_rows(&Connection::open(source_path)?)?;
    match rest {
        [flag, every] if flag == "--verify" => verify(&mut model, &rows, every.parse()?),
        [target_path] => write_copy(&mut model, &rows, target_path),
        _ => bail!("expected <target.db> or --verify <n>"),
    }
}
