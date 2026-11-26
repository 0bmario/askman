//! Scratch ranker for the rules-cc experiment: `examples/rank` with the scoring rules
//! picked by `RULES_VARIANT` (R0..R5). Not wired into the CLI; `src/search.rs` is unchanged.
//! R0: today. R1: no core_command. R2: no niche_variant. R3: neither.
//! R4: R3 + 0.67x when the command name equals a whole query word.
//! R5: R4, or the part of the name before the first `-` equals a query word.
//! The SQL, MAX_DISTANCE, target-OS factor, k=7 and the media gate copy `src/search.rs`.
use askman::{db, embed, media_coverage, search};
use rusqlite::params;
use std::collections::HashMap;
use std::io::BufRead;
use zerocopy::IntoBytes;

const MAX_DISTANCE: f64 = 1.10;
const TARGET_OS_FACTOR: f64 = 0.9;

#[derive(Clone, Copy, PartialEq)]
enum Variant {
    R0,
    R1,
    R2,
    R3,
    R4,
    R5,
}

fn is_core_command(cmd: &str) -> bool {
    cmd == "grep" || (cmd.len() <= 3 && !cmd.starts_with('q') && !cmd.starts_with('z'))
}

fn is_niche_variant(cmd: &str) -> bool {
    cmd.contains('-')
        || cmd.starts_with('q')
        || cmd.starts_with('z')
        || (cmd.ends_with("grep") && cmd != "grep")
        || cmd.ends_with("all")
}

fn names_query_word(cmd: &str, query_words: &[String], variant: Variant) -> bool {
    let cmd = cmd.to_lowercase();
    let stem = cmd.split('-').next().unwrap_or(&cmd);
    query_words
        .iter()
        .any(|word| *word == cmd || (variant == Variant::R5 && word == stem))
}

fn adjust_score(
    variant: Variant,
    cmd: &str,
    query_words: &[String],
    is_target_os: bool,
    raw_distance: f64,
) -> Option<(f64, Vec<String>)> {
    if raw_distance > MAX_DISTANCE {
        return None;
    }
    let mut rules = Vec::new();
    let mut score = raw_distance;
    if is_target_os {
        rules.push(format!("target_os ({TARGET_OS_FACTOR}x)"));
        score *= TARGET_OS_FACTOR;
    }
    let core_rule_on = matches!(variant, Variant::R0 | Variant::R2);
    let niche_rule_on = matches!(variant, Variant::R0 | Variant::R1);
    if core_rule_on && is_core_command(cmd) {
        rules.push("core_command (0.67x)".to_string());
        score *= 0.67;
    } else if niche_rule_on && is_niche_variant(cmd) {
        // With the core rule gone (R1), the niche check applies to every name, as if the
        // first branch were deleted from today's `if / else if`.
        rules.push("niche_variant (1.33x)".to_string());
        score *= 1.33;
    }
    let query_rule_on = matches!(variant, Variant::R4 | Variant::R5);
    if query_rule_on && names_query_word(cmd, query_words, variant) {
        rules.push("query_names_command (0.67x)".to_string());
        score *= 0.67;
    }
    Some((score, rules))
}

fn main() -> anyhow::Result<()> {
    let variant = match std::env::var("RULES_VARIANT")?.as_str() {
        "R0" => Variant::R0,
        "R1" => Variant::R1,
        "R2" => Variant::R2,
        "R3" => Variant::R3,
        "R4" => Variant::R4,
        "R5" => Variant::R5,
        other => anyhow::bail!("RULES_VARIANT must be R0..R5, got {other:?}"),
    };
    db::register_sqlite_vec();
    let app_dir = db::get_app_dir()?;
    let conn = db::get_connection(&db::get_db_path(&app_dir)?)?;
    let embedder = embed::init_model(&app_dir)?;
    let mut stmt = conn.prepare(
        "SELECT command, os = ?2, distance
         FROM pages_vec
         WHERE (os = 'common' OR os = ?2) AND embedding MATCH ?1
         ORDER BY distance
         LIMIT 7;",
    )?;
    for line in std::io::stdin().lock().lines() {
        let line = line?;
        let (os, query) = line
            .split_once('\t')
            .ok_or_else(|| anyhow::anyhow!("expected `os<TAB>query`, got {line:?}"))?;
        let target_os = search::get_target_os(os == "linux", os == "osx", os == "windows");
        let query_words: Vec<String> = query.to_lowercase().split_whitespace().map(String::from).collect();
        let q_vec = embed::embed_query(&embedder, query)?;
        let rows = stmt.query_map(params![q_vec.as_bytes(), target_os.as_str()], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, bool>(1)?, row.get::<_, f64>(2)?))
        })?;
        // First (closest) row per command decides its score, as in perform_search.
        let mut best: HashMap<String, (f64, f64, Vec<String>)> = HashMap::new();
        for row in rows {
            let (cmd, is_target_os, raw) = row?;
            let Some((score, rules)) = adjust_score(variant, &cmd, &query_words, is_target_os, raw) else {
                continue;
            };
            best.entry(cmd).or_insert((score, raw, rules));
        }
        let mut ranked: Vec<_> = best.into_iter().collect();
        ranked.sort_by(|a, b| a.1.0.partial_cmp(&b.1.0).unwrap_or(std::cmp::Ordering::Equal));
        if !media_coverage::allows_answer(query, target_os) {
            ranked.clear();
        }
        let cells: Vec<String> = ranked
            .iter()
            .map(|(cmd, (score, raw, rules))| format!("{cmd}|{score:.4}|{raw:.4}|{}", rules.join("+")))
            .collect();
        println!("{}", cells.join("\t"));
    }
    Ok(())
}
