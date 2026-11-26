//! Scratch example for the synth-index measurement (not part of the CLI).
//! A second vec0 table `task_vec` (rowid = pages_vec rowid, same `command`/`os`) holds one vector per
//! row made from `example_desc` alone. This example ranks queries with it, times a second KNN, and builds it.
//!
//! Usage (HOME must point at a temp dir holding commands-v2.db and the fastembed model cache):
//!   synth_rank rank <variant>          `os<TAB>query` lines on stdin, output as examples/rank.rs
//!   synth_rank time <os> <query...>    one query: today's path + a second KNN, prints stage ms
//!   synth_rank parity <step>           re-embeds every <step>th pages_vec row with the import_tldr text
//!   synth_rank build-task              creates task_vec from example_desc (fp32 AllMiniLML6V2, one text per call)
//! Variants:
//!   base      today's path (search::perform_search)
//!   s1:<a>    fuse per page (1-a)*d_full + a*d_task; a page in one list only keeps that list's distance
//!   s2        task_vec replaces pages_vec
//!   s3        union of both KNN lists, ranked by the full-text distance
use anyhow::{Context, Result, bail};
use askman::search::{CmdData, TargetOs};
use askman::{db, embed, media_coverage, search};
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use rusqlite::{Connection, params};
use std::collections::HashMap;
use std::io::BufRead;
use std::time::Instant;
use zerocopy::IntoBytes;

const K: usize = 7;

fn main() -> Result<()> {
    db::register_sqlite_vec();
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("rank") if args.len() == 2 => rank(&args[1]),
        Some("time") if args.len() >= 3 => time_query(&args[1], &args[2..].join(" ")),
        Some("parity") if args.len() == 2 => parity(args[1].parse()?),
        Some("build-task") if args.len() == 1 => build_task(),
        _ => bail!(
            "usage: synth_rank rank <variant> | time <os> <query...> | parity <step> | build-task"
        ),
    }
}

fn open_db() -> Result<Connection> {
    let app_dir = db::get_app_dir()?;
    db::get_connection(&db::get_db_path(&app_dir)?)
}

/// One KNN result row: rowid, command, is_target_os, distance.
struct Hit {
    rowid: i64,
    command: String,
    is_target_os: bool,
    distance: f64,
}

fn knn(conn: &Connection, table: &str, q_vec: &[f32], target_os: TargetOs) -> Result<Vec<Hit>> {
    let mut stmt = conn.prepare_cached(&format!(
        "SELECT rowid, command, os = ?2, distance FROM {table}
         WHERE (os = 'common' OR os = ?2) AND embedding MATCH ?1
         ORDER BY distance LIMIT {K};"
    ))?;
    let hits = stmt
        .query_map(params![q_vec.as_bytes(), target_os.as_str()], |row| {
            Ok(Hit {
                rowid: row.get(0)?,
                command: row.get(1)?,
                is_target_os: row.get(2)?,
                distance: row.get(3)?,
            })
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    Ok(hits)
}

/// Per page (command), the first hit in distance order, as perform_search keys its map.
fn best_per_page(hits: &[Hit]) -> HashMap<&str, &Hit> {
    let mut best: HashMap<&str, &Hit> = HashMap::new();
    for hit in hits {
        best.entry(hit.command.as_str()).or_insert(hit);
    }
    best
}

/// today's adjust_score, then sort ascending, as perform_search does (examples are not needed here).
fn score_pages(pages: Vec<(String, bool, f64)>) -> Vec<(String, CmdData)> {
    let mut sorted: Vec<(String, CmdData)> = pages
        .into_iter()
        .filter_map(|(cmd, is_target_os, distance)| {
            let (adjusted_score, heuristics) = search::adjust_score(&cmd, is_target_os, distance)?;
            let data = CmdData {
                description: String::new(),
                examples: Vec::new(),
                adjusted_score,
                raw_distance: distance,
                heuristics,
            };
            Some((cmd, data))
        })
        .collect();
    sorted.sort_by(|a, b| {
        a.1.adjusted_score
            .partial_cmp(&b.1.adjusted_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    sorted
}

fn fused(full: &[Hit], task: &[Hit], a: f64) -> Vec<(String, CmdData)> {
    let (full_best, task_best) = (best_per_page(full), best_per_page(task));
    let mut commands: Vec<&str> = full_best.keys().chain(task_best.keys()).copied().collect();
    commands.sort();
    commands.dedup();
    let pages = commands
        .into_iter()
        .map(|cmd| {
            let (f, t) = (full_best.get(cmd), task_best.get(cmd));
            let is_target_os = f.or(t).unwrap().is_target_os;
            let d_full = f.or(t).unwrap().distance;
            let d_task = t.or(f).unwrap().distance;
            (
                cmd.to_string(),
                is_target_os,
                (1.0 - a) * d_full + a * d_task,
            )
        })
        .collect();
    score_pages(pages)
}

fn single(hits: &[Hit]) -> Vec<(String, CmdData)> {
    let mut seen = std::collections::HashSet::new();
    let pages = hits
        .iter()
        .filter(|h| seen.insert(h.command.clone()))
        .map(|h| (h.command.clone(), h.is_target_os, h.distance))
        .collect();
    score_pages(pages)
}

/// Union of both lists' rows, each with its full-text distance, then today's per-page rule.
fn candidates_only(
    conn: &Connection,
    q_vec: &[f32],
    full: &[Hit],
    task: &[Hit],
) -> Result<Vec<(String, CmdData)>> {
    let mut rows: Vec<Hit> = Vec::new();
    let mut stmt = conn
        .prepare_cached("SELECT vec_distance_l2(embedding, ?1) FROM pages_vec WHERE rowid = ?2")?;
    for hit in full.iter().chain(task) {
        if rows.iter().any(|r| r.rowid == hit.rowid) {
            continue;
        }
        let distance = if full.iter().any(|f| f.rowid == hit.rowid) {
            hit.distance
        } else {
            stmt.query_row(params![q_vec.as_bytes(), hit.rowid], |r| r.get(0))?
        };
        rows.push(Hit {
            rowid: hit.rowid,
            command: hit.command.clone(),
            is_target_os: hit.is_target_os,
            distance,
        });
    }
    rows.sort_by(|a, b| a.distance.partial_cmp(&b.distance).unwrap());
    Ok(single(&rows))
}

fn rank(variant: &str) -> Result<()> {
    let conn = open_db()?;
    let embedder = embed::init_model(&db::get_app_dir()?)?;
    for line in std::io::stdin().lock().lines() {
        let line = line?;
        let (os, query) = line.split_once('\t').context("expected `os<TAB>query`")?;
        let target_os = search::get_target_os(os == "linux", os == "osx", os == "windows");
        let q_vec = embed::embed_query(&embedder, query)?;
        let mut ranked = match variant {
            "base" => search::perform_search(&conn, &q_vec, target_os)?,
            "s2" => single(&knn(&conn, "task_vec", &q_vec, target_os)?),
            "s3" => {
                let full = knn(&conn, "pages_vec", &q_vec, target_os)?;
                let task = knn(&conn, "task_vec", &q_vec, target_os)?;
                candidates_only(&conn, &q_vec, &full, &task)?
            }
            v if v.starts_with("s1:") => {
                let a: f64 = v[3..].parse()?;
                let full = knn(&conn, "pages_vec", &q_vec, target_os)?;
                let task = knn(&conn, "task_vec", &q_vec, target_os)?;
                fused(&full, &task, a)
            }
            _ => bail!("unknown variant {variant}"),
        };
        if !media_coverage::allows_answer(query, target_os) {
            ranked.clear();
        }
        let cells: Vec<String> = ranked
            .iter()
            .map(|(cmd, d)| {
                format!(
                    "{}|{:.4}|{:.4}|{}",
                    cmd,
                    d.adjusted_score,
                    d.raw_distance,
                    d.heuristics.join("+")
                )
            })
            .collect();
        println!("{}", cells.join("\t"));
    }
    Ok(())
}

/// Stage ms for one query: today's path (open, init, embed, perform_search, media gate) then the second KNN.
fn time_query(os: &str, query: &str) -> Result<()> {
    let ms = |t: Instant| t.elapsed().as_secs_f64() * 1000.0;
    let t = Instant::now();
    let conn = open_db()?;
    let embedder = embed::init_model(&db::get_app_dir()?)?;
    let init = ms(t);
    let t = Instant::now();
    let target_os = search::get_target_os(os == "linux", os == "osx", os == "windows");
    let q_vec = embed::embed_query(&embedder, query)?;
    let embed_ms = ms(t);
    let t = Instant::now();
    let ranked = search::perform_search(&conn, &q_vec, target_os)?;
    let _ = media_coverage::allows_answer(query, target_os);
    let knn1 = ms(t);
    let t = Instant::now();
    let task = knn(&conn, "task_vec", &q_vec, target_os)?;
    let knn2 = ms(t);
    println!(
        "{init:.3} {embed_ms:.3} {knn1:.3} {knn2:.3} {} {}",
        ranked.len(),
        task.len()
    );
    Ok(())
}

fn fp32_model() -> Result<TextEmbedding> {
    // Same model and cache as import_tldr (fp32 AllMiniLML6V2).
    let options = InitOptions::new(EmbeddingModel::AllMiniLML6V2)
        .with_cache_dir(db::get_app_dir()?.join("models"));
    TextEmbedding::try_new(options)
}

fn embed_one(model: &TextEmbedding, text: String) -> Result<Vec<f32>> {
    Ok(model.embed(vec![text], None)?.remove(0))
}

/// The text import_tldr embeds for one example (src/import_tldr.rs `embedding_text`).
fn full_text(command: &str, description: &str, example_desc: &str, example_cmd: &str) -> String {
    format!(
        "Task: {}. Command: {}. Description: {}. Example: {} {}",
        example_desc, command, description, example_desc, example_cmd
    )
}

fn parity(step: i64) -> Result<()> {
    let conn = open_db()?;
    let model = fp32_model()?;
    let mut stmt = conn.prepare(
        "SELECT rowid, command, description, example_desc, example_cmd, embedding FROM pages_vec WHERE rowid % ?1 = 1",
    )?;
    let rows = stmt.query_map([step], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, String>(3)?,
            r.get::<_, String>(4)?,
            r.get::<_, Vec<u8>>(5)?,
        ))
    })?;
    let (mut n, mut worst) = (0, 0.0f64);
    for row in rows {
        let (rowid, cmd, desc, ex_desc, ex_cmd, blob) = row?;
        let stored: Vec<f32> = blob
            .chunks_exact(4)
            .map(|b| f32::from_le_bytes(b.try_into().unwrap()))
            .collect();
        let fresh = embed_one(&model, full_text(&cmd, &desc, &ex_desc, &ex_cmd))?;
        let dot: f64 = stored
            .iter()
            .zip(&fresh)
            .map(|(a, b)| (*a as f64) * (*b as f64))
            .sum();
        let diff = 1.0 - dot;
        if diff > worst {
            worst = diff;
            println!("rowid {rowid}: 1-cos {diff:.3e}");
        }
        n += 1;
    }
    println!("parity rows={n} max(1-cos)={worst:.3e}");
    Ok(())
}

fn build_task() -> Result<()> {
    let conn = open_db()?;
    let model = fp32_model()?;
    conn.execute_batch(
        "DROP TABLE IF EXISTS task_vec;
         CREATE VIRTUAL TABLE task_vec USING vec0(command TEXT, os TEXT, embedding FLOAT[384]);",
    )?;
    let rows: Vec<(i64, String, String, String)> = conn
        .prepare("SELECT rowid, command, os, example_desc FROM pages_vec ORDER BY rowid")?
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?
        .collect::<rusqlite::Result<_>>()?;
    let start = Instant::now();
    conn.execute_batch("BEGIN")?;
    for (i, (rowid, command, os, example_desc)) in rows.iter().enumerate() {
        let vector = embed_one(&model, example_desc.clone())?;
        conn.execute(
            "INSERT INTO task_vec(rowid, command, os, embedding) VALUES (?1, ?2, ?3, ?4)",
            params![rowid, command, os, vector.as_bytes()],
        )?;
        if i % 1000 == 0 {
            eprintln!("{i}/{} {:.0}s", rows.len(), start.elapsed().as_secs_f64());
        }
    }
    conn.execute_batch("COMMIT")?;
    eprintln!(
        "done {} rows {:.0}s",
        rows.len(),
        start.elapsed().as_secs_f64()
    );
    Ok(())
}
