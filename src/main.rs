use anyhow::Result;

use askman::{cli, db, embed, format, media_coverage, search};
use clap::Parser;
use colored::*;
use std::io::Write;

fn main() -> Result<()> {
    // Required: register sqlite-vec extension before opening any connection
    db::register_sqlite_vec();

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

    try_semantic_search(&conn, &query, &app_dir, target_os, args.verbose)
}

/// Embeds the query, runs KNN against sqlite-vec, ranks results, and prints output.
fn try_semantic_search(
    conn: &rusqlite::Connection,
    query: &str,
    app_dir: &std::path::Path,
    target_os: search::TargetOs,
    verbose: bool,
) -> Result<()> {
    let embedder = embed::init_model(app_dir)?;
    let q_vec = embed::embed_query(&embedder, query)?;
    let mut sorted = search::perform_search(conn, &q_vec, target_os)?;
    if !media_coverage::allows_answer(query, target_os) {
        sorted.clear();
    }

    // A reader that closes early (`askman ... | head -1`) is not an error.
    match print_results(&mut std::io::stdout().lock(), &sorted, verbose) {
        Err(e) if e.kind() == std::io::ErrorKind::BrokenPipe => Ok(()),
        result => Ok(result?),
    }
}

fn print_results(
    out: &mut impl Write,
    sorted: &[(String, search::CmdData)],
    verbose: bool,
) -> std::io::Result<()> {
    for (i, (cmd, data)) in sorted.iter().enumerate().take(3) {
        let mut show_count = if i == 0 { data.examples.len() } else { 0 };

        // only show more than 1 command if it's exceptionally close in meaning to the top result
        if i > 0 {
            let top_score = sorted[0].1.adjusted_score;
            let current_score = sorted[i].1.adjusted_score;
            // if it's very close, we can show one example for it
            if current_score - top_score < 0.05 {
                show_count = 1;
            } else {
                continue; // Skip printing this command entirely if it's too irrelevant compared to the top hit
            }
        }

        writeln!(out, "{}", cmd.bold().green())?;
        if verbose {
            let rules = if data.heuristics.is_empty() {
                "none".to_string()
            } else {
                data.heuristics.join(", ")
            };
            writeln!(
                out,
                "{}",
                format!(
                    "(Distance: {:.4} | Raw: {:.4} | Rules: {})",
                    data.adjusted_score, data.raw_distance, rules
                )
                .bright_black()
            )?;
        }

        // Clean up description (strip "More information" links)
        let clean_desc = if let Some(idx) = data.description.find(" More information:") {
            &data.description[..idx]
        } else {
            &data.description
        };
        writeln!(out, "{}", clean_desc)?;

        if show_count > 0 && !data.examples.is_empty() {
            writeln!(out, "\n{}", "Examples:".underline())?;
            for (ex_desc, ex_cmd) in data.examples.iter().take(show_count) {
                writeln!(out, "  {}", ex_desc)?;
                writeln!(out, "   {}", format::highlight_command(ex_cmd))?;
                writeln!(out)?;
            }
        }
        writeln!(out)?;
    }

    if sorted.is_empty() {
        writeln!(out, "No good matches found.")?;
    }

    Ok(())
}
