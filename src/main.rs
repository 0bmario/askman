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
use std::io::Write;
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

    /// Force search for Linux commands
    #[arg(long)]
    linux: bool,

    /// Force search for macOS commands
    #[arg(long)]
    osx: bool,

    /// Force search for Windows commands
    #[arg(long)]
    windows: bool,
}

// (description, [(example_desc, example_cmd)], adjusted_score)
type CmdData = (String, Vec<(String, String)>, f64);
type CmdMap = HashMap<String, CmdData>;

/// Global data directory: ~/.local/share/askman (linux) or ~/Library/Application Support/askman (mac)
fn get_app_dir() -> PathBuf {
    let mut path = dirs::data_dir().unwrap_or_else(|| PathBuf::from("."));
    path.push("askman");
    if !path.exists() {
        std::fs::create_dir_all(&path).unwrap_or_default();
    }
    path
}

/// Resolves commands.db path. Falls back to downloading from GitHub on first run.
fn get_db_path(app_dir: &std::path::Path) -> Result<PathBuf> {
    // Check next to executable first (backward compat for local dev installs)
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(dir) = exe_path.parent() {
            let local_db_path = dir.join("commands.db");
            if local_db_path.exists() {
                return Ok(local_db_path);
            }
        }
    }

    let global_db_path = app_dir.join("commands.db");

    if !global_db_path.exists() {
        println!("Downloading initial commands database (this only happens once)...");
        let response = reqwest::blocking::get(
            "https://raw.githubusercontent.com/cito-lito/askman/main/commands.db",
        )?;

        if response.status().is_success() {
            let mut file = std::fs::File::create(&global_db_path)?;
            let bytes = response.bytes()?;
            file.write_all(&bytes)?;
            println!("Download complete.");
        } else {
            return Err(anyhow::anyhow!(
                "Failed to download database: HTTP {}",
                response.status()
            ));
        }
    }

    Ok(global_db_path)
}

fn main() -> Result<()> {
    // Required: register sqlite-vec extension before opening any connection
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
    let db_path = get_db_path(&app_dir)?;
    let conn = Connection::open(db_path)?;

    // CLI flags override auto-detection; default maps to host OS
    let target_os = if args.linux {
        "linux"
    } else if args.osx {
        "osx"
    } else if args.windows {
        "windows"
    } else {
        match std::env::consts::OS {
            "macos" => "osx",
            "windows" => "windows",
            _ => "linux", // Defaults freebsd/openbsd/linux to linux
        }
    };

    try_semantic_search(&conn, &query, &app_dir, target_os)
}

/// Embeds the query, runs KNN against sqlite-vec, ranks results, and prints output.
fn try_semantic_search(
    conn: &Connection,
    query: &str,
    app_dir: &std::path::Path,
    target_os: &str,
) -> Result<()> {
    let embed_options =
        InitOptions::new(EmbeddingModel::AllMiniLML6V2).with_cache_dir(app_dir.join("models"));
    let embedder = TextEmbedding::try_new(embed_options)?;

    let q_vec = embedder.embed(vec![query], None)?[0].clone();
    let q_blob = q_vec.as_bytes();

    let mut stmt = conn.prepare(
        "SELECT command, description, example_desc, example_cmd, distance
         FROM pages_vec
         WHERE (os = 'common' OR os = ?2) AND embedding MATCH ?1
         ORDER BY distance
         LIMIT 7;",
    )?;

    let results = stmt.query_map(params![q_blob, target_os], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, f64>(4)?,
        ))
    })?;

    let mut command_map: CmdMap = HashMap::new();

    // Descriptions linking to these domains get a slight relevance boost
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

        // Distance threshold: prevents completely unrelated matches (this is until a better solution)
        if score > 1.10 {
            continue;
        }

        let is_official = official_sites.iter().any(|&site| desc.contains(site));
        let mut adjusted_score = if is_official { score * 1.2 } else { score };

        // Heuristic to prefer basic unix commands over niche variants (this is until a better solution)
        if cmd == "grep" || (cmd.len() <= 3 && !cmd.starts_with('q') && !cmd.starts_with('z')) {
            adjusted_score *= 1.50; // Boost core commands like 'mv', 'cp', 'rm', 'grep'
        } else if cmd.contains('-')
            || cmd.starts_with('q')
            || cmd.starts_with('z')
            || (cmd.ends_with("grep") && cmd != "grep")
            || cmd.ends_with("all")
        {
            adjusted_score *= 0.75; // Penalize niche variants like 'qmv', 'zgrep', 'egrep', 'docker-cp'
        }

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
        let mut show_count = if i == 0 { examples.len() } else { 0 };

        // only show more than 1 command if it's exceptionally close in meaning to the top result
        if i > 0 {
            let top_score = sorted[0].1.2;
            let current_score = sorted[i].1.2;
            // if it's very close, we can show one example for it
            if top_score - current_score < 0.05 {
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

                // We want to highlight the core command, flags, and arguments nicely.
                // 1. Split the command into parts
                // 2. The first word (the command) gets one color
                // 3. Flags (-flags, --flags) get another
                // 4. Variables (which we detect via the original {{}} brackets) get another

                let mut highlighted_cmd = String::new();
                let mut in_variable = false;

                // Simple tokenizer that respects the {{var}} syntax from tldr before stripping it
                let mut current_word = String::new();
                let mut i = 0;
                let chars: Vec<char> = ex_cmd.chars().collect();

                while i < chars.len() {
                    // Check for variable start {{
                    if i + 1 < chars.len() && chars[i] == '{' && chars[i + 1] == '{' {
                        if !current_word.is_empty() {
                            highlighted_cmd.push_str(&colorize_shell_word(
                                &current_word,
                                highlighted_cmd.is_empty(),
                            ));
                            current_word.clear();
                        }
                        in_variable = true;
                        i += 2;
                        continue;
                    }

                    // Check for variable end }}
                    if i + 1 < chars.len() && chars[i] == '}' && chars[i + 1] == '}' {
                        if !current_word.is_empty() {
                            // Variables are colored yellow
                            highlighted_cmd.push_str(&current_word.yellow().to_string());
                            current_word.clear();
                        }
                        in_variable = false;
                        i += 2;
                        continue;
                    }

                    if chars[i].is_whitespace() && !in_variable {
                        if !current_word.is_empty() {
                            highlighted_cmd.push_str(&colorize_shell_word(
                                &current_word,
                                highlighted_cmd.is_empty(),
                            ));
                            current_word.clear();
                        }
                        highlighted_cmd.push(chars[i]);
                    } else {
                        current_word.push(chars[i]);
                    }
                    i += 1;
                }

                // Push any remaining text
                if !current_word.is_empty() {
                    if in_variable {
                        highlighted_cmd.push_str(&current_word.yellow().to_string());
                    } else {
                        highlighted_cmd.push_str(&colorize_shell_word(
                            &current_word,
                            highlighted_cmd.is_empty(),
                        ));
                    }
                }

                println!("   {}", highlighted_cmd);
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

fn colorize_shell_word(word: &str, is_first: bool) -> String {
    if is_first {
        word.green().bold().to_string()
    } else if word.starts_with('-') {
        word.cyan().to_string()
    } else if word.starts_with('[') || word.starts_with(']') || word.contains('|') {
        word.bright_black().to_string() // visually mute bash syntax like [-f|--force]
    } else {
        // Normal text (paths, strings not in variables)
        word.to_string()
    }
}
