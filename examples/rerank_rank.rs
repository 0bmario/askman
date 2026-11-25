//! E6b scratch ranker (not wired into the CLI): `examples/rank.rs`, then reorders the surviving
//! candidates by cross-encoder score. Same stdin/stdout format as `rank`, so `eval/score.py --rank` works.
//! Env: `RERANK_MODEL_DIR` (model.onnx + tokenizer files), `RERANK_VARIANT` = `r1` | `r2`.
//! Pair text: the query, and the `import_tldr` embedding text of the command's best (nearest) KNN row,
//! which is `examples[0]` because perform_search pushes rows in distance order.
//! Printed score is a distance-like value, `d = 1 - sigmoid(logit)`, sorted ascending:
//! r1 uses d as is; r2 multiplies d by 0.9 for target-OS pages (today's TARGET_OS_FACTOR).
use anyhow::{Context, bail};
use askman::{db, embed, media_coverage, search};
use fastembed::{
    RerankInitOptionsUserDefined, TextRerank, TokenizerFiles, UserDefinedRerankingModel,
};
use std::io::BufRead;
use std::path::PathBuf;

const TARGET_OS_FACTOR: f64 = 0.9;

fn load_reranker(dir: PathBuf) -> anyhow::Result<TextRerank> {
    let read =
        |name: &str| std::fs::read(dir.join(name)).with_context(|| format!("reading {name}"));
    let model = UserDefinedRerankingModel::new(
        dir.join("model.onnx"),
        TokenizerFiles {
            tokenizer_file: read("tokenizer.json")?,
            config_file: read("config.json")?,
            special_tokens_map_file: read("special_tokens_map.json")?,
            tokenizer_config_file: read("tokenizer_config.json")?,
        },
    );
    Ok(TextRerank::try_new_from_user_defined(
        model,
        RerankInitOptionsUserDefined::default(),
    )?)
}

fn main() -> anyhow::Result<()> {
    let keep_target_os_rule = match std::env::var("RERANK_VARIANT")?.as_str() {
        "r1" => false,
        "r2" => true,
        other => bail!("RERANK_VARIANT must be r1 or r2, got {other:?}"),
    };
    let reranker = load_reranker(std::env::var("RERANK_MODEL_DIR")?.into())?;

    db::register_sqlite_vec();
    let app_dir = db::get_app_dir()?;
    let conn = db::get_connection(&db::get_db_path(&app_dir)?)?;
    let embedder = embed::init_model(&app_dir)?;
    for line in std::io::stdin().lock().lines() {
        let line = line?;
        let (os, query) = line
            .split_once('\t')
            .ok_or_else(|| anyhow::anyhow!("expected `os<TAB>query`, got {line:?}"))?;
        let target_os = search::get_target_os(os == "linux", os == "osx", os == "windows");
        let q_vec = embed::embed_query(&embedder, query)?;
        let mut ranked = search::perform_search(&conn, &q_vec, target_os)?;
        if !media_coverage::allows_answer(query, target_os) {
            ranked.clear();
        }
        if ranked.is_empty() {
            println!();
            continue;
        }

        let texts: Vec<String> = ranked
            .iter()
            .map(|(cmd, data)| {
                let (example_desc, example_cmd) = &data.examples[0];
                format!(
                    "Task: {example_desc}. Command: {cmd}. Description: {}. Example: {example_desc} {example_cmd}",
                    data.description
                )
            })
            .collect();
        let text_refs: Vec<&str> = texts.iter().map(String::as_str).collect();
        // At most 7 pairs, one call.
        let results = reranker.rerank(query, text_refs, false, Some(7))?;

        let mut cells: Vec<(f64, String)> = results
            .iter()
            .map(|result| {
                let (cmd, data) = &ranked[result.index];
                let is_target_os = data.heuristics.iter().any(|h| h.starts_with("target_os"));
                let mut distance = 1.0 - 1.0 / (1.0 + (-f64::from(result.score)).exp());
                if keep_target_os_rule && is_target_os {
                    distance *= TARGET_OS_FACTOR;
                }
                (distance, format!("{cmd}|{distance:.4}|{:.4}|ce={:.3}", data.raw_distance, result.score))
            })
            .collect();
        cells.sort_by(|a, b| a.0.total_cmp(&b.0));
        let cells: Vec<String> = cells.into_iter().map(|(_, cell)| cell).collect();
        println!("{}", cells.join("\t"));
    }
    Ok(())
}
