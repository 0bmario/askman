//! Scratch benchmark for the speed-knn experiment (not part of the CLI, not shipped).
//! Times the 0.3.10 query path stage by stage, with optional candidate changes.
//!
//!   speed_bench time <variant> <os> <query words...>   one query; prints stage timings
//!   speed_bench tok                                    tokenizer load breakdown (one process)
//!
//! Variants (comma-separated flags, or `base`):
//!   mmap   PRAGMA mmap_size on the connection before the KNN statement
//!   par    load the tokenizer on a second thread while the ORT session loads
use anyhow::{Context, Result, bail};
use askman::{db, media_coverage, search};
use ort::session::Session;
use ort::session::builder::GraphOptimizationLevel;
use ort::value::Tensor;
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tokenizers::{Tokenizer, TruncationParams};

fn ms(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0
}

fn snapshot_dir(app_dir: &Path) -> Result<PathBuf> {
    let repo = app_dir.join("models/models--Xenova--all-MiniLM-L6-v2");
    let commit = std::fs::read_to_string(repo.join("refs/main")).context("model cache missing")?;
    Ok(repo.join("snapshots").join(commit.trim()))
}

fn configure(mut tokenizer: Tokenizer) -> Result<Tokenizer> {
    tokenizer.with_padding(None);
    tokenizer
        .with_truncation(Some(TruncationParams {
            max_length: 512,
            ..Default::default()
        }))
        .map_err(anyhow::Error::msg)?;
    Ok(tokenizer)
}

fn load_tokenizer(snapshot: &Path) -> Result<Tokenizer> {
    configure(Tokenizer::from_file(snapshot.join("tokenizer.json")).map_err(anyhow::Error::msg)?)
}

fn load_session(app_dir: &Path, snapshot: &Path) -> Result<Session> {
    let commit = snapshot.file_name().unwrap().to_string_lossy();
    let file = app_dir.join("models").join(format!(
        "model_quantized-optimized-{commit}-ort-1.20.0.onnx"
    ));
    let threads = std::thread::available_parallelism()?.get();
    Ok(Session::builder()?
        .with_intra_threads(threads)?
        .with_optimization_level(GraphOptimizationLevel::Disable)?
        .commit_from_file(file)?)
}

fn main() -> Result<()> {
    let main_epoch_ns = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("time") if args.len() >= 4 => {
            time_query(main_epoch_ns, &args[1], &args[2], &args[3..].join(" "))
        }
        Some("tok") => tok_breakdown(),
        _ => bail!("usage: speed_bench time <variant> <os> <query...> | tok"),
    }
}

/// Prints: main_epoch_ns db tok_load session tokenize infer prepare search gate in_main count
fn time_query(main_epoch_ns: u128, variant: &str, os: &str, query: &str) -> Result<()> {
    let mmap = variant.split(',').any(|flag| flag == "mmap");
    let par = variant.split(',').any(|flag| flag == "par");
    let total = Instant::now();

    let start = Instant::now();
    db::register_sqlite_vec();
    let app_dir = db::get_app_dir()?;
    // Opened directly (0.3.10's get_connection), so a changed get_connection does not leak into `base`.
    let conn = rusqlite::Connection::open(db::get_db_path(&app_dir)?)?;
    if mmap {
        conn.pragma_update(None, "mmap_size", 256 * 1024 * 1024)?;
    }
    let db_ms = ms(start);

    let snapshot = snapshot_dir(&app_dir)?;
    let (tokenizer, session, tok_ms, session_ms) = if par {
        let start = Instant::now();
        let (tokenizer, session) = std::thread::scope(|scope| {
            let tokenizer = scope.spawn(|| load_tokenizer(&snapshot));
            let session = load_session(&app_dir, &snapshot);
            (tokenizer.join().unwrap(), session)
        });
        // Combined wall time is reported as "session"; tokenizer column 0.
        (tokenizer?, session?, 0.0, ms(start))
    } else {
        let start = Instant::now();
        let tokenizer = load_tokenizer(&snapshot)?;
        let tok_ms = ms(start);
        let start = Instant::now();
        let session = load_session(&app_dir, &snapshot)?;
        (tokenizer, session, tok_ms, ms(start))
    };

    let start = Instant::now();
    let encoding = tokenizer.encode(query, true).map_err(anyhow::Error::msg)?;
    let tokenize_ms = ms(start);

    let start = Instant::now();
    let as_i64 = |values: &[u32]| values.iter().map(|&v| i64::from(v)).collect::<Vec<i64>>();
    let shape = [1, encoding.len()];
    let mask = encoding.get_attention_mask();
    let outputs = session.run(ort::inputs![
        "input_ids" => Tensor::from_array((shape, as_i64(encoding.get_ids())))?,
        "attention_mask" => Tensor::from_array((shape, as_i64(mask)))?,
        "token_type_ids" => Tensor::from_array((shape, as_i64(encoding.get_type_ids())))?,
    ]?)?;
    let (output_shape, hidden) = outputs["last_hidden_state"].try_extract_raw_tensor::<f32>()?;
    let dim = output_shape[2] as usize;
    let mut sums = vec![0f32; dim];
    let mut kept = 0f32;
    for (token, &keep) in mask.iter().enumerate() {
        if keep == 0 {
            continue;
        }
        kept += 1.0;
        for (sum, value) in sums.iter_mut().zip(&hidden[token * dim..(token + 1) * dim]) {
            *sum += value;
        }
    }
    let means: Vec<f32> = sums.iter().map(|sum| sum / kept.max(1.0)).collect();
    let norm = means.iter().map(|v| v * v).sum::<f32>().sqrt();
    let q_vec: Vec<f32> = means.iter().map(|v| v / (norm + 1e-12)).collect();
    let infer_ms = ms(start);

    let target_os = search::get_target_os(os == "linux", os == "osx", os == "windows");
    // The CLI's first prepare also reads the schema; time it on its own, then the
    // CLI's search (prepare again, scan, scoring) and media gate.
    let start = Instant::now();
    drop(conn.prepare(
        "SELECT command, os = ?2, description, example_desc, example_cmd, distance
         FROM pages_vec
         WHERE (os = 'common' OR os = ?2) AND embedding MATCH ?1
         ORDER BY distance
         LIMIT 7;",
    )?);
    let prepare_ms = ms(start);
    let start = Instant::now();
    let mut ranked = search::perform_search(&conn, &q_vec, target_os)?;
    let knn_ms = ms(start);
    let start = Instant::now();
    if !media_coverage::allows_answer(query, target_os) {
        ranked.clear();
    }
    let post_ms = ms(start);

    println!(
        "{main_epoch_ns} {db_ms:.3} {tok_ms:.3} {session_ms:.3} {tokenize_ms:.3} {infer_ms:.3} {prepare_ms:.3} {knn_ms:.3} {post_ms:.3} {:.3} {}",
        ms(total),
        ranked.len()
    );
    Ok(())
}

fn tok_breakdown() -> Result<()> {
    let app_dir = db::get_app_dir()?;
    let path = snapshot_dir(&app_dir)?.join("tokenizer.json");
    let start = Instant::now();
    let text = std::fs::read_to_string(&path)?;
    let read_ms = ms(start);
    let start = Instant::now();
    let value: serde_json::Value = serde_json::from_str(&text)?;
    let value_ms = ms(start);
    drop(value);
    let start = Instant::now();
    let tokenizer: Tokenizer = text.parse().map_err(anyhow::Error::msg)?;
    let parse_ms = ms(start);
    let start = Instant::now();
    let _ = configure(tokenizer)?;
    let configure_ms = ms(start);
    println!(
        "read {read_ms:.3} json_value {value_ms:.3} tokenizer_from_str {parse_ms:.3} configure {configure_ms:.3}"
    );
    Ok(())
}
