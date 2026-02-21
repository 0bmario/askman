use anyhow::Result;
use clap::Parser;
use colored::*;
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use rusqlite::Connection;
use rusqlite::ffi::sqlite3_auto_extension;
use rusqlite::params;
use sqlite_vec::sqlite3_vec_init;
use std::collections::HashMap;
use std::collections::hash_map::Entry;
use std::path::PathBuf;
use zerocopy::IntoBytes;

/// askman – offline CLI helper
#[derive(Parser, Debug)]
#[command(
    version,
    about = "Ask natural language questions about Unix/Linux commands."
)]
struct Args {
    #[arg(required_unless_present = "clean")]
    question: Vec<String>,

    /// Remove the global settings, database, and model cache to uninstall
    #[arg(long, short = 'c')]
    clean: bool,
}

type CmdData = (String, Vec<(String, String)>, f64);
type CmdMap = HashMap<String, CmdData>;

fn get_app_dir() -> PathBuf {
    let mut path = dirs::data_dir().unwrap_or_else(|| PathBuf::from("."));
    path.push("askman");
    if !path.exists() {
        std::fs::create_dir_all(&path).unwrap_or_default();
    }
    path
}

fn get_db_path(app_dir: &std::path::Path) -> PathBuf {
    // First, check if db is right next to the executable, for backward compatibility or local installs
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(dir) = exe_path.parent() {
            let db_path = dir.join("commands.db");
            if db_path.exists() {
                return db_path;
            }
        }
    }
    app_dir.join("commands.db")
}

fn main() -> Result<()> {
    unsafe {
        sqlite3_auto_extension(Some(std::mem::transmute(sqlite3_vec_init as *const ())));
    }

    let args = Args::parse();
    let app_dir = get_app_dir();

    if args.clean {
        println!("Cleaning up askman application data...");
        if app_dir.exists() {
            if let Err(e) = std::fs::remove_dir_all(&app_dir) {
                eprintln!(
                    "Failed to remove data directory: {}. Please delete it manually at {:?}",
                    e, app_dir
                );
            } else {
                println!(
                    "Successfully removed configuration, database, and models from {:?}",
                    app_dir
                );
            }
        } else {
            println!("No data directory found at {:?}", app_dir);
        }
        return Ok(());
    }

    let query = args.question.join(" ");
    let db_path = get_db_path(&app_dir);
    let conn = Connection::open(db_path)?;

    try_semantic_search(&conn, &query, &app_dir)
}

fn try_semantic_search(conn: &Connection, query: &str, app_dir: &std::path::Path) -> Result<()> {
    let embed_options =
        InitOptions::new(EmbeddingModel::AllMiniLML6V2).with_cache_dir(app_dir.join("models"));
    let embedder = TextEmbedding::try_new(embed_options)?;

    let q_vec = embedder.embed(vec![query], None)?[0].clone();
    let q_blob = q_vec.as_bytes();

    let mut stmt = conn.prepare(
        "SELECT command, description, example_desc, example_cmd, distance
         FROM pages_vec
         WHERE embedding MATCH ?1
         ORDER BY distance
         LIMIT 7;",
    )?;

    let results = stmt.query_map(params![q_blob], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, f64>(4)?,
        ))
    })?;

    let mut command_map: CmdMap = HashMap::new();
    let official_sites = [
        "gnu.",
        "kernel.",
        "man7.",
        "manned.",
        "linux.",
        "man.openbsd",
        "man.freebsd",
        "greenwoodsoftware.",
    ];

    for result in results {
        let (cmd, desc, ex_desc, ex_cmd, score) = result?;
        if score < 0.7 {
            continue;
        }

        let is_official = official_sites.iter().any(|&site| desc.contains(site));
        let adjusted_score = if is_official { score * 1.2 } else { score };

        match command_map.entry(cmd.clone()) {
            Entry::Vacant(e) => {
                e.insert((desc, vec![(ex_desc, ex_cmd)], adjusted_score));
            }
            Entry::Occupied(mut o) => {
                o.get_mut().1.push((ex_desc, ex_cmd));
            }
        }
    }

    let mut sorted: Vec<(&String, &CmdData)> = command_map.iter().collect();
    sorted.sort_by(|a, b| {
        b.1.2
            .partial_cmp(&a.1.2)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    for (i, (cmd, (desc, examples, _))) in sorted.iter().enumerate().take(3) {
        println!("{}", cmd.bold().green());
        println!("{}", desc);

        if !examples.is_empty() {
            println!("\n{}", "Examples:".underline());
            let show_count = if i < 2 { examples.len() } else { 1 };
            for (ex_desc, ex_cmd) in examples.iter().take(show_count) {
                println!("  {}", ex_desc);
                println!("   {}", ex_cmd.cyan());
                println!();
            }
        }
        println!();
    }

    if sorted.is_empty() {
        println!("No good matches found.");
    }

    Ok(())
}
