use anyhow::Result;

use askman::{cli, db, embed, format, search};
use clap::Parser;
use colored::*;
use rusqlite::ffi::sqlite3_auto_extension;
use sqlite_vec::sqlite3_vec_init;

fn main() -> Result<()> {
    // Required: register sqlite-vec extension before opening any connection
    #[allow(clippy::missing_transmute_annotations)]
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

    try_semantic_search(&conn, &query, &app_dir, target_os, args.verbose, args.json)
}

/// Embeds the query, runs KNN against sqlite-vec, ranks results, and prints output.
fn try_semantic_search(
    conn: &rusqlite::Connection,
    query: &str,
    app_dir: &std::path::Path,
    target_os: search::TargetOs,
    verbose: bool,
    output_json: bool,
) -> Result<()> {
    let embedder = embed::init_model(app_dir)?;
    let q_vec = embed::embed_query(&embedder, query)?;
    let mut sorted = search::perform_search(conn, query, &q_vec, target_os, output_json)?;

    if output_json {
        // JSON policy blocks thin complex results; hydrate the top hit with more examples
        // so strong single-intent queries are less likely to be rejected as under-specified.
        // Follow-up after exercising this: ensure hydration respects the requested OS or tags each example with its platform.
        let _ = search::hydrate_top_result_examples(
            conn,
            &mut sorted,
            query,
            target_os,
            true,
            search::HYDRATE_MIN_EXAMPLES,
            search::HYDRATE_MAX_EXAMPLES,
        )?;

        let mut results_json = Vec::new();
        for (i, (cmd, data)) in sorted.iter().enumerate().take(2) {
            // Expose partial-intent mismatches directly to agents (`pass`/`warn` + missing terms).
            let intent = search::evaluate_intent_coverage(query, cmd, data);

            // Clean up description (strip "More information" and "See also" links)
            let mut clean_desc = data.description.as_str();
            if let Some(idx) = clean_desc.find(" More information:") {
                clean_desc = &clean_desc[..idx];
            }
            if let Some(idx) = clean_desc.find(" See also:") {
                clean_desc = &clean_desc[..idx];
            }

            // confidence for standard LLM agents:
            // polynomial curve 1.0 - (dist / max)^7 to keep scores high
            // this is a try of normalizing the  cosine distance to a confidence score
            let ratio = (data.adjusted_score / search::MAX_DISTANCE).clamp(0.0, 1.0);
            let confidence = 1.0 - ratio.powf(7.0);

            // noise reduction:
            // If we are not at least 50% confident, avoid it.
            // If the absolute best result (#1) is a slam dunk (> 90%), and this result
            // is a distant second (trailing by > 10%), also avoid it.
            if i > 0 {
                if confidence < 0.50 {
                    break;
                }

                // Need to compute the #1 result's confidence for the delta check
                let top_score = sorted[0].1.adjusted_score;
                let top_ratio = (top_score / search::MAX_DISTANCE).clamp(0.0, 1.0);
                let top_confidence = 1.0 - top_ratio.powf(7.0);

                if top_confidence > 0.90 && (top_confidence - confidence) > 0.10 {
                    break;
                }
            }

            let mut result_obj = serde_json::json!({
                "command": cmd,
                "platform": data.platform,
                "description": clean_desc.trim_end_matches([' ', '\n']).replace("[", "").replace("]", ""),
                "confidence": (confidence * 10000.0).round() / 10000.0,
                "intent": {
                    "coverage": (intent.score * 10000.0).round() / 10000.0,
                    "status": if intent.strong { "pass" } else { "warn" },
                    "missing_terms": intent.missing_terms
                },
                "examples": data.examples.iter().map(|(desc, ex_cmd)| {
                    serde_json::json!({
                        "description": desc.replace("[", "").replace("]", ""),
                        "syntax": ex_cmd
                    })
                }).collect::<Vec<_>>(),
            });

            if verbose {
                if let Some(obj) = result_obj.as_object_mut() {
                    obj.insert(
                        "adjusted_distance".to_string(),
                        serde_json::json!(data.adjusted_score),
                    );
                    obj.insert(
                        "raw_distance".to_string(),
                        serde_json::json!(data.raw_distance),
                    );
                    obj.insert(
                        "heuristics_applied".to_string(),
                        serde_json::json!(data.heuristics),
                    );
                    obj.insert(
                        "intent_matched_terms".to_string(),
                        serde_json::json!(intent.matched_terms),
                    );
                }
            }
            results_json.push(result_obj);
        }

        let output = serde_json::json!({
            "query": query,
            "os": target_os.as_str(),
            "results": results_json
        });

        println!("{}", serde_json::to_string_pretty(&output)?);
        return Ok(());
    }

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

        println!("{}", cmd.bold().green());
        if verbose {
            let rules = if data.heuristics.is_empty() {
                "none".to_string()
            } else {
                data.heuristics.join(", ")
            };
            println!(
                "{}",
                format!(
                    "(Distance: {:.4} | Raw: {:.4} | Rules: {})",
                    data.adjusted_score, data.raw_distance, rules
                )
                .bright_black()
            );
        }

        // Clean up description (strip "More information" and "See also" links)
        let mut clean_desc = data.description.as_str();
        if let Some(idx) = clean_desc.find(" More information:") {
            clean_desc = &clean_desc[..idx];
        }
        if let Some(idx) = clean_desc.find(" See also:") {
            clean_desc = &clean_desc[..idx];
        }
        println!("{}", clean_desc);

        if show_count > 0 && !data.examples.is_empty() {
            println!("\n{}", "Examples:".underline());
            for (ex_desc, ex_cmd) in data.examples.iter().take(show_count) {
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
