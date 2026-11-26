use anyhow::{Context, Result};
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use ort::session::Session;
use ort::session::builder::GraphOptimizationLevel;
use ort::value::Tensor;
use std::path::{Path, PathBuf};
use tokenizers::{Tokenizer, TruncationParams};

// The int8 query encoder matches the fp32 vectors in the commands database (built by
// import_tldr with AllMiniLML6V2) on the eval set, at a quarter of the download.
// These are the files fastembed's AllMiniLML6V2Q uses, read from fastembed's hf-hub cache
// so installs that already have them download nothing.
const MODEL_REPO_DIR: &str = "models--Xenova--all-MiniLM-L6-v2";
const MODEL_FILE: &str = "onnx/model_quantized.onnx";
const TOKENIZER_FILE: &str = "tokenizer.json";
/// fastembed's default; the model's tokenizer_config.json allows 512 as well.
const MAX_TOKENS: usize = 512;

pub struct QueryModel {
    tokenizer: Tokenizer,
    session: Session,
}

/// Loads the query model, downloading it on first use. The ORT session comes from a
/// graph-optimized copy of the model made once on this machine, which skips the graph
/// optimization (about a third of model start-up) on every later query.
pub fn init_model(app_dir: &Path) -> Result<QueryModel> {
    let cache_dir = model_cache_dir(app_dir);
    let snapshot = match cached_snapshot(&cache_dir) {
        Some(snapshot) => snapshot,
        None => {
            download_model(&cache_dir)?;
            cached_snapshot(&cache_dir).with_context(|| {
                format!(
                    "query model files missing in {} after download",
                    cache_dir.display()
                )
            })?
        }
    };
    let optimized = app_dir.join("models").join(optimized_file_name());
    Ok(QueryModel {
        tokenizer: load_tokenizer(&snapshot.join(TOKENIZER_FILE))?,
        session: load_session(&snapshot.join(MODEL_FILE), &optimized)?,
    })
}

pub fn embed_query(model: &QueryModel, query: &str) -> Result<Vec<f32>> {
    let encoding = model
        .tokenizer
        .encode(query, true)
        .map_err(anyhow::Error::msg)?;
    let as_i64 = |values: &[u32]| values.iter().map(|&v| i64::from(v)).collect::<Vec<i64>>();
    let shape = [1, encoding.len()];
    let attention_mask = encoding.get_attention_mask();
    let outputs = model.session.run(ort::inputs![
        "input_ids" => Tensor::from_array((shape, as_i64(encoding.get_ids())))?,
        "attention_mask" => Tensor::from_array((shape, as_i64(attention_mask)))?,
        "token_type_ids" => Tensor::from_array((shape, as_i64(encoding.get_type_ids())))?,
    ]?)?;
    let (output_shape, hidden) = outputs["last_hidden_state"].try_extract_raw_tensor::<f32>()?;
    let dim = output_shape[2] as usize;

    // Mean pooling over the attention mask, then L2 normalisation, summed in the same order
    // as fastembed 4.8 (`pooling::mean`, `normalize`) so the vectors are bit-identical.
    let mut sums = vec![0f32; dim];
    let mut kept_tokens = 0f32;
    for (token, &keep) in attention_mask.iter().enumerate() {
        if keep == 0 {
            continue;
        }
        kept_tokens += 1.0;
        for (sum, value) in sums.iter_mut().zip(&hidden[token * dim..(token + 1) * dim]) {
            *sum += value;
        }
    }
    let means: Vec<f32> = sums.iter().map(|sum| sum / kept_tokens.max(1.0)).collect();
    let norm = means.iter().map(|v| v * v).sum::<f32>().sqrt();
    Ok(means.iter().map(|v| v / (norm + 1e-12)).collect())
}

/// Where fastembed keeps its hf-hub cache: `HF_HOME` if set, else the data dir's `models/`.
fn model_cache_dir(app_dir: &Path) -> PathBuf {
    std::env::var_os("HF_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| app_dir.join("models"))
}

/// The hf-hub snapshot directory, if it holds both files the query model needs.
fn cached_snapshot(cache_dir: &Path) -> Option<PathBuf> {
    let repo = cache_dir.join(MODEL_REPO_DIR);
    let commit = std::fs::read_to_string(repo.join("refs/main")).ok()?;
    let snapshot = repo.join("snapshots").join(commit.trim());
    let has_files = snapshot.join(MODEL_FILE).exists() && snapshot.join(TOKENIZER_FILE).exists();
    has_files.then_some(snapshot)
}

/// Lets fastembed download the model into its cache, as askman 0.3.8 did.
fn download_model(cache_dir: &Path) -> Result<()> {
    let options = InitOptions::new(EmbeddingModel::AllMiniLML6V2Q)
        .with_show_download_progress(true)
        .with_cache_dir(cache_dir.to_path_buf());
    TextEmbedding::try_new(options).with_context(|| {
        format!(
            "failed to download embedding model AllMiniLML6V2Q into {}",
            cache_dir.display()
        )
    })?;
    Ok(())
}

/// Keyed by ONNX Runtime version: an optimized graph is only valid for the runtime that wrote it.
fn optimized_file_name() -> String {
    format!("model_quantized-optimized-ort-{}.onnx", ort_version())
}

fn ort_version() -> String {
    // SAFETY: OrtGetApiBase returns a static struct whose GetVersionString returns a static C string.
    unsafe {
        let get_version = (*ort::sys::OrtGetApiBase())
            .GetVersionString
            .expect("ONNX Runtime exposes GetVersionString");
        std::ffi::CStr::from_ptr(get_version())
            .to_string_lossy()
            .into_owned()
    }
}

fn load_tokenizer(path: &Path) -> Result<Tokenizer> {
    let mut tokenizer = Tokenizer::from_file(path).map_err(anyhow::Error::msg)?;
    // As fastembed does for one text: no padding, truncation at 512. tokenizer.json itself
    // pads and truncates to 128, which would change the vectors.
    tokenizer.with_padding(None);
    tokenizer
        .with_truncation(Some(TruncationParams {
            max_length: MAX_TOKENS,
            ..Default::default()
        }))
        .map_err(anyhow::Error::msg)?;
    // fastembed also re-adds special_tokens_map.json's tokens; tokenizer.json already holds
    // them as special tokens, so that changes nothing (the reference test has a "[cls]" query).
    Ok(tokenizer)
}

/// Loads the optimized model, creating it if missing or unreadable. A cache that cannot be
/// used must not break queries, so that case falls back to the original model.
fn load_session(original: &Path, optimized: &Path) -> Result<Session> {
    let load_error = if optimized.exists() {
        match load_optimized(optimized) {
            Ok(session) => return Ok(session),
            Err(error) => Some(error),
        }
    } else {
        None
    };
    match create_optimized(original, optimized) {
        Ok(session) => {
            if let Some(error) = load_error {
                eprintln!(
                    "askman: rebuilt the optimized query model at {} ({error:#})",
                    optimized.display()
                );
            }
            Ok(session)
        }
        Err(error) => {
            eprintln!(
                "askman: cannot use the optimized query model at {} ({error:#}); loading the original model",
                optimized.display()
            );
            load_original(original)
        }
    }
}

fn load_optimized(optimized: &Path) -> Result<Session> {
    Ok(Session::builder()?
        .with_optimization_level(GraphOptimizationLevel::Disable)?
        .commit_from_file(optimized)?)
}

/// Optimizes the graph once (Level2 holds no CPU-specific layout changes) and saves it.
/// ORT writes to a per-process temp name that is then renamed, so concurrent first runs
/// and killed runs never leave a partial file under the final name.
fn create_optimized(original: &Path, optimized: &Path) -> Result<Session> {
    if let Some(dir) = optimized.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let mut tmp_name = optimized.as_os_str().to_owned();
    tmp_name.push(format!(".tmp-{}", std::process::id()));
    let tmp_path = PathBuf::from(tmp_name);
    let result = (|| -> Result<Session> {
        let session = Session::builder()?
            .with_optimization_level(GraphOptimizationLevel::Level2)?
            .with_optimized_model_path(&tmp_path)?
            .commit_from_file(original)?;
        std::fs::rename(&tmp_path, optimized)?;
        Ok(session)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&tmp_path);
    }
    result
}

fn load_original(original: &Path) -> Result<Session> {
    Session::builder()?
        .commit_from_file(original)
        .with_context(|| format!("failed to load the query model {}", original.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Vectors from fastembed 4.8 `AllMiniLML6V2Q` (askman 0.3.8's query path), one
    /// `query<TAB>space-separated f32` line each; f32 Display round-trips exactly.
    fn reference_vectors() -> Vec<(String, Vec<f32>)> {
        let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/data/query_vectors.tsv");
        let text = std::fs::read_to_string(&path).unwrap();
        text.lines()
            .map(|line| {
                let (query, cells) = line.split_once('\t').unwrap();
                let vector = cells.split(' ').map(|cell| cell.parse().unwrap()).collect();
                (query.to_string(), vector)
            })
            .collect()
    }

    fn max_difference(a: &[f32], b: &[f32]) -> f32 {
        assert_eq!(a.len(), b.len());
        a.iter()
            .zip(b)
            .map(|(x, y)| (x - y).abs())
            .fold(0f32, f32::max)
    }

    // Reads the model from the askman data dir under HOME and never downloads it. CI runs
    // it without network access after the smoke test has fetched the model.
    //
    // The fixture was made on macOS aarch64. ORT's CPU kernels round differently on other
    // CPUs, so there the fixture only bounds the difference, and exactness is checked against
    // fastembed 4.8 run live on the same machine.
    #[test]
    #[ignore = "needs the query model in the askman data dir"]
    fn query_vectors_match_fastembed() -> Result<()> {
        let app_dir = crate::db::get_app_dir()?;
        let snapshot = cached_snapshot(&model_cache_dir(&app_dir))
            .context("query model not in the askman data dir")?;
        let tokenizer = load_tokenizer(&snapshot.join(TOKENIZER_FILE))?;
        let original = snapshot.join(MODEL_FILE);
        let scratch = std::env::temp_dir().join(format!("askman-embed-{}", std::process::id()));
        let optimized = scratch.join("model.onnx");

        // First run (creates the optimized file), later runs, and the fallback.
        let sessions = [
            ("created", load_session(&original, &optimized)?),
            ("loaded", load_optimized(&optimized)?),
            ("original", load_original(&original)?),
        ];
        let fastembed = TextEmbedding::try_new(
            InitOptions::new(EmbeddingModel::AllMiniLML6V2Q)
                .with_cache_dir(model_cache_dir(&app_dir)),
        )?;
        let fixture_is_exact = cfg!(all(target_os = "macos", target_arch = "aarch64"));
        let fixture_bound = if fixture_is_exact { 0.0 } else { 1e-6 };
        let references = reference_vectors();
        assert!(references.len() >= 6);
        for (query, fixture) in &references {
            let live = fastembed.embed(vec![query], None)?.remove(0);
            let fixture_difference = max_difference(&live, fixture);
            println!("fastembed vs fixture {fixture_difference:e}: {query:?}");
            assert!(
                fixture_difference <= fixture_bound,
                "fastembed, query {query:?}"
            );
        }
        for (name, session) in sessions {
            let model = QueryModel {
                tokenizer: tokenizer.clone(),
                session,
            };
            for (query, fixture) in &references {
                let actual = embed_query(&model, query)?;
                let live = fastembed.embed(vec![query], None)?.remove(0);
                let live_difference = max_difference(&actual, &live);
                let fixture_difference = max_difference(&actual, fixture);
                println!(
                    "{name}: vs fastembed {live_difference:e}, vs fixture {fixture_difference:e}: {query:?}"
                );
                assert_eq!(live_difference, 0.0, "{name} session, query {query:?}");
                assert!(
                    fixture_difference <= fixture_bound,
                    "{name} session, query {query:?}"
                );
            }
        }
        std::fs::remove_dir_all(&scratch)?;
        Ok(())
    }
}
