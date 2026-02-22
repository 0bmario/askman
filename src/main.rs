mod cli;
mod db;
mod embed;
mod format;
mod search;

use anyhow::Result;
use clap::Parser;
use colored::*;
use rusqlite::ffi::sqlite3_auto_extension;
use sqlite_vec::sqlite3_vec_init;

fn main() -> Result<()> {
    // Required: register sqlite-vec extension before opening any connection
    unsafe {
        sqlite3_auto_extension(Some(std::mem::transmute(sqlite3_vec_init as *const ())));
    }

    let args = cli::Args::parse();

    if args.clean {
        let app_dir = db::get_app_dir_path();
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

    let app_dir = db::get_app_dir()?;
    let query = args.question.join(" ");
    let db_path = db::get_db_path(&app_dir)?;
    let conn = db::get_connection(&db_path)?;

    // CLI flags override auto-detection; default maps to host OS
    let target_os = search::get_target_os(args.linux, args.osx, args.windows);

    try_semantic_search(&conn, &query, &app_dir, target_os)
}

/// Embeds the query, runs KNN against sqlite-vec, ranks results, and prints output.
fn try_semantic_search(
    conn: &rusqlite::Connection,
    query: &str,
    app_dir: &std::path::Path,
    target_os: &str,
) -> Result<()> {
    let embedder = embed::init_model(app_dir)?;
    let q_vec = embed::embed_query(&embedder, query)?;

    let sorted = search::perform_search(conn, &q_vec, target_os)?;

    for (i, (cmd, (desc, examples, _))) in sorted.iter().enumerate().take(3) {
        let mut show_count = if i == 0 { examples.len() } else { 0 };

        // only show more than 1 command if it's exceptionally close in meaning to the top result
        if i > 0 {
            let top_score = sorted[0].1.2;
            let current_score = sorted[i].1.2;
            // if it's very close, we can show one example for it
            if current_score - top_score < 0.05 {
                show_count = 1;
            } else {
                continue; // Skip printing this command entirely if it's too irrelevant compared to the top hit
            }
        }

        println!("{}", cmd.bold().green());

        // Clean up description (strip "More information" links)
        let clean_desc = if let Some(idx) = desc.find(" More information:") {
            &desc[..idx]
        } else {
            desc
        };
        println!("{}", clean_desc);

        if show_count > 0 && !examples.is_empty() {
            println!("\n{}", "Examples:".underline());
            for (ex_desc, ex_cmd) in examples.iter().take(show_count) {
                println!("  {}", ex_desc);
                println!("   {}", format::highlight_command(ex_cmd));
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
