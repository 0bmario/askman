//! Scratch benchmark for the startup-bench experiment (not part of the CLI).
//! Times the query path stage by stage and compares ways of creating the ORT session
//! for the same int8 AllMiniLML6V2Q model.
//!
//! Usage (HOME must point at a temp dir holding commands.db and the fastembed model cache):
//!   startup_bench time <variant> <os> <query words...>  one query, prints stage timings
//!   startup_bench vectors <variant>                      `query` lines on stdin, prints vectors
//!   startup_bench optimize <level 2|3> <out file>        saves an offline-optimized model
//!                                                        (`.ort` extension -> ORT format)
//! Variants:
//!   v0          fastembed 4.8 as shipped (embed::init_model + embed::embed_query)
//!   v1          direct ort session from the same file, ORT's default level and threads
//!   v2          v1 with intra-op threads = 1
//!   v3:<n>      models/opt/model-l2.onnx, optimization disabled, n intra threads (0 = default)
//!   v4:<n>      models/opt/model-l2.ort, the same as v3 in ORT format
use anyhow::{Context, Result, bail};
use askman::{db, embed, media_coverage, search};
use ort::session::Session;
use ort::session::builder::GraphOptimizationLevel;
use ort::value::Tensor;
use std::io::BufRead;
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tokenizers::{Tokenizer, TruncationParams};

/// fastembed's InitOptions default; the tokenizer config caps it at 512 as well.
const MAX_LENGTH: usize = 512;

fn main() -> Result<()> {
    // Wall-clock time at `main`, so the harness can split pre-main from in-process time.
    let main_epoch_ns = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("time") if args.len() >= 4 => time_query(main_epoch_ns, &args[1], &args[2], &args[3..].join(" ")),
        Some("vectors") if args.len() == 2 => print_vectors(&args[1]),
        Some("optimize") if args.len() == 3 => optimize(&args[1], Path::new(&args[2])),
        _ => bail!("usage: startup_bench time <variant> <os> <query...> | vectors <variant> | optimize <2|3> <out>"),
    }
}

enum Embedder {
    Fastembed(fastembed::TextEmbedding),
    Direct { tokenizer: Tokenizer, session: Session, needs_token_type_ids: bool },
}

/// Stage times in ms; `tokenizer_ms` is NaN for v0 because fastembed loads it inside `init_model`.
struct InitTimes {
    tokenizer_ms: f64,
    session_ms: f64,
}

fn ms_since(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0
}

fn snapshot_dir(app_dir: &Path) -> Result<PathBuf> {
    let repo = app_dir.join("models/models--Xenova--all-MiniLM-L6-v2");
    let reference = std::fs::read_to_string(repo.join("refs/main")).context("model cache missing")?;
    Ok(repo.join("snapshots").join(reference.trim()))
}

fn load_tokenizer(snapshot: &Path) -> Result<Tokenizer> {
    let mut tokenizer = Tokenizer::from_file(snapshot.join("tokenizer.json")).map_err(anyhow::Error::msg)?;
    // Same as fastembed for a single text: no padding (BatchLongest of one), truncate at 512.
    // tokenizer.json itself asks for fixed padding to 128 and truncation at 128.
    tokenizer.with_padding(None);
    tokenizer
        .with_truncation(Some(TruncationParams { max_length: MAX_LENGTH, ..Default::default() }))
        .map_err(anyhow::Error::msg)?;
    Ok(tokenizer)
}

fn init(variant: &str, app_dir: &Path) -> Result<(Embedder, InitTimes)> {
    if variant == "v0" {
        let start = Instant::now();
        let model = embed::init_model(app_dir)?;
        let times = InitTimes { tokenizer_ms: f64::NAN, session_ms: ms_since(start) };
        return Ok((Embedder::Fastembed(model), times));
    }
    let snapshot = snapshot_dir(app_dir)?;
    let opt_dir = app_dir.join("models/opt");
    let (model_file, level, threads) = match variant.split_once(':') {
        None if variant == "v1" => (snapshot.join("onnx/model_quantized.onnx"), None, 0),
        None if variant == "v2" => (snapshot.join("onnx/model_quantized.onnx"), None, 1),
        Some(("v3", n)) => (opt_dir.join("model-l2.onnx"), Some(GraphOptimizationLevel::Disable), n.parse()?),
        Some(("v4", n)) => (opt_dir.join("model-l2.ort"), Some(GraphOptimizationLevel::Disable), n.parse()?),
        _ => bail!("unknown variant {variant}"),
    };

    let start = Instant::now();
    let tokenizer = load_tokenizer(&snapshot)?;
    let tokenizer_ms = ms_since(start);

    let start = Instant::now();
    let mut builder = Session::builder()?;
    if let Some(level) = level {
        builder = builder.with_optimization_level(level)?;
    }
    if threads > 0 {
        builder = builder.with_intra_threads(threads)?;
    }
    let session = builder.commit_from_file(&model_file)?;
    let session_ms = ms_since(start);

    let needs_token_type_ids = session.inputs.iter().any(|input| input.name == "token_type_ids");
    let embedder = Embedder::Direct { tokenizer, session, needs_token_type_ids };
    Ok((embedder, InitTimes { tokenizer_ms, session_ms }))
}

/// Mean pooling over the attention mask, then L2 normalisation, as fastembed 4.8 does.
fn embed_direct(tokenizer: &Tokenizer, session: &Session, needs_token_type_ids: bool, query: &str) -> Result<Vec<f32>> {
    let encoding = tokenizer.encode(query, true).map_err(anyhow::Error::msg)?;
    let to_i64 = |values: &[u32]| values.iter().map(|&v| v as i64).collect::<Vec<i64>>();
    let token_count = encoding.len();
    let mask = to_i64(encoding.get_attention_mask());
    let mut inputs = ort::inputs![
        "input_ids" => Tensor::from_array(([1, token_count], to_i64(encoding.get_ids())))?,
        "attention_mask" => Tensor::from_array(([1, token_count], mask.clone()))?,
    ]?;
    if needs_token_type_ids {
        let type_ids = Tensor::from_array(([1, token_count], to_i64(encoding.get_type_ids())))?;
        inputs.push(("token_type_ids".into(), type_ids.into()));
    }
    let outputs = session.run(inputs)?;
    let (shape, hidden) = outputs["last_hidden_state"].try_extract_raw_tensor::<f32>()?;
    let dim = shape[2] as usize;

    let mut pooled = vec![0f32; dim];
    let mut kept_tokens = 0f32;
    for (token, &keep) in mask.iter().enumerate() {
        if keep == 0 {
            continue;
        }
        kept_tokens += 1.0;
        for (sum, value) in pooled.iter_mut().zip(&hidden[token * dim..(token + 1) * dim]) {
            *sum += value;
        }
    }
    let pooled: Vec<f32> = pooled.iter().map(|sum| sum / kept_tokens.max(1.0)).collect();
    let norm = pooled.iter().map(|v| v * v).sum::<f32>().sqrt();
    Ok(pooled.iter().map(|v| v / (norm + 1e-12)).collect())
}

fn embed_query(embedder: &Embedder, query: &str) -> Result<Vec<f32>> {
    match embedder {
        Embedder::Fastembed(model) => embed::embed_query(model, query),
        Embedder::Direct { tokenizer, session, needs_token_type_ids } => {
            embed_direct(tokenizer, session, *needs_token_type_ids, query)
        }
    }
}

/// Follows main.rs: database first, then model, embed, KNN, media gate.
/// Prints: main_epoch_ns db_ms tokenizer_ms session_ms embed_ms knn_ms total_ms result_count
fn time_query(main_epoch_ns: u128, variant: &str, os: &str, query: &str) -> Result<()> {
    let total = Instant::now();
    let start = Instant::now();
    db::register_sqlite_vec();
    let app_dir = db::get_app_dir()?;
    let conn = db::get_connection(&db::get_db_path(&app_dir)?)?;
    let db_ms = ms_since(start);

    let (embedder, init_times) = init(variant, &app_dir)?;

    let start = Instant::now();
    let q_vec = embed_query(&embedder, query)?;
    let embed_ms = ms_since(start);

    let start = Instant::now();
    let target_os = search::get_target_os(os == "linux", os == "osx", os == "windows");
    let mut ranked = search::perform_search(&conn, &q_vec, target_os)?;
    if !media_coverage::allows_answer(query, target_os) {
        ranked.clear();
    }
    let knn_ms = ms_since(start);

    println!(
        "{main_epoch_ns} {db_ms:.3} {:.3} {:.3} {embed_ms:.3} {knn_ms:.3} {:.3} {}",
        init_times.tokenizer_ms,
        init_times.session_ms,
        ms_since(total),
        ranked.len()
    );
    Ok(())
}

fn print_vectors(variant: &str) -> Result<()> {
    let app_dir = db::get_app_dir()?;
    let (embedder, _) = init(variant, &app_dir)?;
    for line in std::io::stdin().lock().lines() {
        let vector = embed_query(&embedder, &line?)?;
        let cells: Vec<String> = vector.iter().map(|v| format!("{v:e}")).collect();
        println!("{}", cells.join(" "));
    }
    Ok(())
}

fn optimize(level: &str, out: &Path) -> Result<()> {
    let level = match level {
        "2" => GraphOptimizationLevel::Level2,
        "3" => GraphOptimizationLevel::Level3,
        _ => bail!("level must be 2 or 3"),
    };
    let app_dir = db::get_app_dir()?;
    let source = snapshot_dir(&app_dir)?.join("onnx/model_quantized.onnx");
    let mut builder = Session::builder()?.with_optimization_level(level)?.with_optimized_model_path(out)?;
    if out.extension().is_some_and(|ext| ext == "ort") {
        builder = builder.with_config_entry("session.save_model_format", "ORT")?;
    }
    builder.commit_from_file(&source)?;
    println!("{}", std::fs::metadata(out)?.len());
    Ok(())
}
