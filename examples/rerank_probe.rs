//! E6 kill test (scratch, not wired into the CLI): fresh-process cost of a cross-encoder.
//! `rerank_probe <base|rerank> <linux|osx|windows> <query...>`
//! Both arms load the 0.3.7 query model, embed the query and fetch the 7 KNN rows the CLI fetches.
//! `rerank` also loads `<app_dir>/reranker/` (ONNX + tokenizer files) and scores the 7
//! (query, row text) pairs, the row text in the format `import_tldr` embeds.
use anyhow::{Context, bail};
use askman::{db, embed, search};
use fastembed::{
    RerankInitOptionsUserDefined, TextRerank, TokenizerFiles, UserDefinedRerankingModel,
};
use rusqlite::params;
use zerocopy::IntoBytes;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [arm, os, query_words @ ..] = args.as_slice() else {
        bail!("usage: rerank_probe <base|rerank> <linux|osx|windows> <query...>");
    };
    let query = query_words.join(" ");
    let target_os = search::get_target_os(os == "linux", os == "osx", os == "windows");

    db::register_sqlite_vec();
    let app_dir = db::get_app_dir()?;
    let conn = db::get_connection(&db::get_db_path(&app_dir)?)?;
    let embedder = embed::init_model(&app_dir)?;
    let q_vec = embed::embed_query(&embedder, &query)?;

    // Same KNN as search::perform_search, but keeping the raw rows.
    let mut stmt = conn.prepare(
        "SELECT command, description, example_desc, example_cmd
         FROM pages_vec
         WHERE (os = 'common' OR os = ?2) AND embedding MATCH ?1
         ORDER BY distance
         LIMIT 7;",
    )?;
    let rows: Vec<(String, String)> = stmt
        .query_map(params![q_vec.as_bytes(), target_os.as_str()], |row| {
            let (command, description, example_desc, example_cmd): (String, String, String, String) =
                (row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?);
            let text = format!(
                "Task: {example_desc}. Command: {command}. Description: {description}. Example: {example_desc} {example_cmd}"
            );
            Ok((command, text))
        })?
        .collect::<Result<_, _>>()?;

    match arm.as_str() {
        "base" => {
            for (command, _) in &rows {
                println!("{command}");
            }
        }
        "rerank" => {
            let dir = app_dir.join("reranker");
            let read = |name: &str| {
                std::fs::read(dir.join(name)).with_context(|| format!("reading {name}"))
            };
            let model = UserDefinedRerankingModel::new(
                dir.join("model.onnx"),
                TokenizerFiles {
                    tokenizer_file: read("tokenizer.json")?,
                    config_file: read("config.json")?,
                    special_tokens_map_file: read("special_tokens_map.json")?,
                    tokenizer_config_file: read("tokenizer_config.json")?,
                },
            );
            let reranker =
                TextRerank::try_new_from_user_defined(model, RerankInitOptionsUserDefined::default())?;
            let texts: Vec<&str> = rows.iter().map(|(_, text)| text.as_str()).collect();
            for result in reranker.rerank(query.as_str(), texts, false, None)? {
                println!("{}\t{:.4}", rows[result.index].0, result.score);
            }
        }
        other => bail!("unknown arm {other:?}, expected base or rerank"),
    }
    Ok(())
}
