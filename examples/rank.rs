//! Ranks eval queries through the same path as the CLI:
//! embed -> sqlite-vec KNN -> adjust_score -> media gate.
//! Reads `target_os<TAB>query` lines on stdin and prints one line per query:
//! `command|adjusted_score|raw_distance|rules` cells separated by tabs.
use askman::{db, embed, media_coverage, search};
use std::io::BufRead;

fn main() -> anyhow::Result<()> {
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
        let cells: Vec<String> = ranked
            .iter()
            .map(|(cmd, data)| {
                format!(
                    "{}|{:.4}|{:.4}|{}",
                    cmd,
                    data.adjusted_score,
                    data.raw_distance,
                    data.heuristics.join("+")
                )
            })
            .collect();
        println!("{}", cells.join("\t"));
    }
    Ok(())
}
