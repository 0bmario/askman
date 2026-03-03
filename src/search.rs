use rusqlite::Connection;
use rusqlite::params;
use std::collections::HashMap;
use std::collections::HashSet;
use std::collections::hash_map::Entry;
use zerocopy::IntoBytes;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TargetOs {
    Linux,
    Osx,
    Windows,
}

impl TargetOs {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Linux => "linux",
            Self::Osx => "osx",
            Self::Windows => "windows",
        }
    }
}

#[derive(Debug)]
pub struct CmdData {
    pub description: String,
    pub platform: String,
    pub examples: Vec<(String, String)>,
    pub adjusted_score: f64,
    pub raw_distance: f64,
    pub heuristics: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct IntentCoverage {
    pub score: f64,
    pub matched_terms: Vec<String>,
    pub missing_terms: Vec<String>,
    pub strong: bool,
}

pub type CmdMap = HashMap<String, CmdData>;

/// Domains that indicate an "official" man page source
const OFFICIAL_SITES: &[&str] = &[
    "gnu.",
    "kernel.",
    "man7.",
    "manned.",
    "linux.",
    "man.openbsd",
    "man.freebsd",
    "greenwoodsoftware.",
];

/// Whitelist of core canonical UNIX utilities that should always be prioritized
pub const CORE_COMMANDS: &[&str] = &[
    "tar",
    "grep",
    "find",
    "sed",
    "awk",
    "curl",
    "wget",
    "cat",
    "ls",
    "rm",
    "cp",
    "mv",
    "echo",
    "kill",
    "chmod",
    "chown",
    "ssh",
    "scp",
    "rsync",
    "df",
    "du",
    "head",
    "tail",
    "ps",
    "top",
    "htop",
    "less",
    "more",
    "nano",
    "vim",
    "vi",
    "emacs",
    "mkdir",
    "rmdir",
    "touch",
    "ln",
    "pwd",
    "cd",
    "bash",
    "sh",
    "zsh",
    "ping",
    "netstat",
    "ip",
    "ifconfig",
    "dig",
    "nslookup",
    "git",
    "docker",
    "kubectl",
    "systemctl",
    "journalctl",
    "uname",
    "whoami",
    "history",
    "clear",
    "exit",
    "date",
    "cal",
    "uptime",
    "w",
    "who",
    "su",
    "sudo",
    "passwd",
    "adduser",
    "usermod",
    "userdel",
    "groupadd",
    "groupmod",
    "groupdel",
    "gzip",
    "gunzip",
    "zip",
    "unzip",
    "bzip2",
    "bunzip2",
    "xz",
    "unxz",
    "7z",
    "ffmpeg",
    "convert",
    "jq",
    "yq",
    "cut",
    "sort",
    "uniq",
    "tr",
    "wc",
    "tee",
    "xargs",
    "fd",
    "rg",
    "ag",
    "tmux",
    "screen",
];

/// Cosine distance threshold (0 = identical, 2 = opposite): filters out unrelated matches.
/// sqlite-vec's vec0 table returns cosine distance by default via the `distance` column.
/// See: https://alexgarcia.xyz/sqlite-vec/api-reference.html#vec_distance_cosine
pub const MAX_DISTANCE: f64 = 1.10;
pub const HYDRATE_MIN_EXAMPLES: usize = 3;
pub const HYDRATE_MAX_EXAMPLES: usize = 12;
pub const INTENT_COMPLEX_MIN_TERMS: usize = 3;
pub const INTENT_MIN_SCORE_SIMPLE: f64 = 0.50;
pub const INTENT_MIN_SCORE_COMPLEX: f64 = 0.60;

const INTENT_STOPWORDS: &[&str] = &[
    "a", "an", "and", "as", "at", "by", "for", "from", "get", "how", "in", "into", "list", "of",
    "on", "or", "run", "show", "the", "then", "to", "using", "with",
];

pub fn get_target_os(linux: bool, osx: bool, windows: bool) -> TargetOs {
    match (linux, osx, windows) {
        (true, _, _) => TargetOs::Linux,
        (_, true, _) => TargetOs::Osx,
        (_, _, true) => TargetOs::Windows,
        _ => match std::env::consts::OS {
            "macos" => TargetOs::Osx,
            "windows" => TargetOs::Windows,
            _ => TargetOs::Linux,
        },
    }
}

/// Pure scoring function: adjusts raw distance based on command name and description heuristics.
/// Returns `None` if the result should be filtered out (score above threshold).
pub fn adjust_score(
    query: &str,
    cmd: &str,
    desc: &str,
    raw_distance: f64,
) -> Option<(f64, Vec<String>)> {
    if raw_distance > MAX_DISTANCE {
        return None;
    }

    let mut applied_heuristics = Vec::new();
    let is_official = OFFICIAL_SITES.iter().any(|&site| desc.contains(site));
    let mut score = if is_official {
        applied_heuristics.push("official_site (0.8x)".to_string());
        raw_distance * 0.8
    } else {
        raw_distance
    };

    // Explicit Intent Multiplier: If the user explicitly typed the command in the query
    let query_words: Vec<&str> = query.split_whitespace().collect();
    if query_words.contains(&cmd) {
        applied_heuristics.push("exact_match (0.5x)".to_string());
        score *= 0.5; // Massive boost for explicit intent
    }

    if CORE_COMMANDS.contains(&cmd) {
        applied_heuristics.push("core_command (0.67x)".to_string());
        score *= 0.67; // Boost canonical core tools
    } else if cmd.contains('-')
        || cmd.starts_with('q')
        || cmd.starts_with('z')
        || (cmd.ends_with("grep") && cmd != "grep")
        || cmd.ends_with("all")
    {
        applied_heuristics.push("niche_variant (1.33x)".to_string());
        score *= 1.33; // Penalize niche variants
    }

    Some((score, applied_heuristics))
}

pub fn perform_search(
    conn: &Connection,
    query: &str,
    q_vec: &[f32],
    target_os: TargetOs,
    cross_platform: bool,
) -> anyhow::Result<Vec<(String, CmdData)>> {
    let q_blob = q_vec.as_bytes();

    let mut results_vec = Vec::new();

    if cross_platform {
        let mut stmt = conn.prepare(
            "SELECT command, os, description, example_desc, example_cmd, distance
             FROM pages_vec
             WHERE embedding MATCH ?1
             ORDER BY distance
             LIMIT 23;",
        )?;
        let mapped = stmt.query_map(params![q_blob], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, f64>(5)?,
            ))
        })?;
        for r in mapped {
            results_vec.push(r?);
        }
    } else {
        let mut stmt = conn.prepare(
            "SELECT command, description, example_desc, example_cmd, distance
             FROM pages_vec
             WHERE (os = 'common' OR os = ?2) AND embedding MATCH ?1
             ORDER BY distance
             LIMIT 23;",
        )?;
        let mapped = stmt.query_map(params![q_blob, target_os.as_str()], |row| {
            Ok((
                row.get::<_, String>(0)?,
                target_os.as_str().to_string(), // os_tag
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, f64>(4)?,
            ))
        })?;
        for r in mapped {
            results_vec.push(r?);
        }
    }

    let mut command_map: CmdMap = HashMap::new();

    for (cmd, os_tag, desc, ex_desc, ex_cmd, raw_distance) in results_vec {
        let (adjusted_score, heuristics) = match adjust_score(query, &cmd, &desc, raw_distance) {
            Some(s) => s,
            None => {
                continue;
            }
        };

        match command_map.entry(cmd.clone()) {
            Entry::Vacant(e) => {
                e.insert(CmdData {
                    description: desc,
                    platform: os_tag,
                    examples: vec![(ex_desc, ex_cmd)],
                    adjusted_score,
                    raw_distance,
                    heuristics,
                });
            }
            Entry::Occupied(mut o) => {
                o.get_mut().examples.push((ex_desc, ex_cmd));
            }
        }
    }

    let mut sorted: Vec<(String, CmdData)> = command_map.into_iter().collect();
    sorted.sort_by(|a, b| {
        a.1.adjusted_score
            .partial_cmp(&b.1.adjusted_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    Ok(sorted)
}

/// If the top result is thin, fetch more examples for that command directly from DB.
pub fn hydrate_top_result_examples(
    conn: &Connection,
    sorted: &mut [(String, CmdData)],
    query: &str,
    target_os: TargetOs,
    cross_platform: bool,
    min_examples: usize,
    max_examples: usize,
) -> anyhow::Result<usize> {
    let Some((command, data)) = sorted.first_mut() else {
        return Ok(0);
    };

    if data.examples.len() >= min_examples {
        return Ok(0);
    }

    // Avoid enriching unrelated top hits; only hydrate when query clearly targets this command.
    if !query_mentions_command_family(query, command) || !is_simple_intent_query(query) {
        return Ok(0);
    }

    hydrate_examples_for_command(conn, command, data, target_os, cross_platform, max_examples)
}

fn query_mentions_command_family(query: &str, command: &str) -> bool {
    let family = command.split('-').next().unwrap_or(command);
    let query_words: Vec<String> = query
        .split_whitespace()
        .map(|w| {
            w.trim_matches(|c: char| !c.is_ascii_alphanumeric() && c != '-')
                .to_ascii_lowercase()
        })
        .filter(|w| !w.is_empty())
        .collect();

    let command_lc = command.to_ascii_lowercase();
    let family_lc = family.to_ascii_lowercase();

    query_words
        .iter()
        .any(|w| w == &command_lc || w == &family_lc)
}

fn is_simple_intent_query(query: &str) -> bool {
    let q = query.to_ascii_lowercase();
    // Multi-step intent is better handled by decomposition instead of auto-expanding one command.
    if q.contains(" and ") || q.contains(" then ") || q.contains(';') || q.contains(" with ") {
        return false;
    }

    let words = q.split_whitespace().count();
    words <= 6
}

pub fn evaluate_intent_coverage(query: &str, command: &str, data: &CmdData) -> IntentCoverage {
    // Lightweight lexical coverage check used as an execution guard for partial semantic matches.
    let query_terms = extract_intent_terms(query);
    if query_terms.is_empty() {
        return IntentCoverage {
            score: 1.0,
            matched_terms: vec![],
            missing_terms: vec![],
            strong: true,
        };
    }

    let mut corpus = String::new();
    corpus.push_str(command);
    corpus.push(' ');
    corpus.push_str(&data.description);
    corpus.push(' ');
    for (desc, ex_cmd) in &data.examples {
        corpus.push_str(desc);
        corpus.push(' ');
        corpus.push_str(ex_cmd);
        corpus.push(' ');
    }

    let corpus_terms = extract_intent_terms(&corpus);
    let corpus_set: HashSet<&str> = corpus_terms.iter().map(String::as_str).collect();

    let mut matched_terms = Vec::new();
    let mut missing_terms = Vec::new();
    for term in &query_terms {
        if corpus_set.contains(term.as_str()) {
            matched_terms.push(term.clone());
        } else {
            missing_terms.push(term.clone());
        }
    }

    let score = matched_terms.len() as f64 / query_terms.len() as f64;
    // Demand higher coverage for longer queries because they encode more explicit constraints.
    let min_score = if query_terms.len() >= INTENT_COMPLEX_MIN_TERMS {
        INTENT_MIN_SCORE_COMPLEX
    } else {
        INTENT_MIN_SCORE_SIMPLE
    };

    IntentCoverage {
        score,
        matched_terms,
        missing_terms,
        strong: score >= min_score,
    }
}

fn extract_intent_terms(text: &str) -> Vec<String> {
    let mut terms = Vec::new();
    let mut seen = HashSet::new();

    for raw in text.split_whitespace() {
        let token = raw
            .trim_matches(|c: char| !c.is_ascii_alphanumeric() && c != '-')
            .to_ascii_lowercase();
        if token.is_empty() {
            continue;
        }
        if INTENT_STOPWORDS.contains(&token.as_str()) {
            continue;
        }
        push_intent_term(&token, &mut terms, &mut seen);
        if token.contains('-') {
            for part in token.split('-') {
                push_intent_term(part, &mut terms, &mut seen);
            }
        }
    }

    terms
}

fn push_intent_term(token: &str, terms: &mut Vec<String>, seen: &mut HashSet<String>) {
    if token.len() < 3 {
        return;
    }
    if INTENT_STOPWORDS.contains(&token) {
        return;
    }
    if seen.insert(token.to_string()) {
        terms.push(token.to_string());
    }
}

fn hydrate_examples_for_command(
    conn: &Connection,
    command: &str,
    data: &mut CmdData,
    target_os: TargetOs,
    cross_platform: bool,
    max_examples: usize,
) -> anyhow::Result<usize> {
    if data.examples.len() >= max_examples {
        return Ok(0);
    }

    let mut seen: HashSet<(String, String)> = data.examples.iter().cloned().collect();
    let mut added = 0usize;

    if cross_platform {
        let mut stmt = conn.prepare(
            "SELECT os, description, example_desc, example_cmd
             FROM pages_vec
             WHERE command = ?1
             ORDER BY rowid",
        )?;
        let mapped = stmt.query_map(params![command], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
            ))
        })?;

        for row in mapped {
            if data.examples.len() >= max_examples {
                break;
            }

            let (_os, desc, ex_desc, ex_cmd) = row?;
            // Keep unique examples only; duplicates inflate depth without improving evidence.
            if seen.insert((ex_desc.clone(), ex_cmd.clone())) {
                if data.description.is_empty() {
                    data.description = desc;
                }
                data.examples.push((ex_desc, ex_cmd));
                added += 1;
            }
        }
    } else {
        let mut stmt = conn.prepare(
            "SELECT description, example_desc, example_cmd
             FROM pages_vec
             WHERE command = ?1 AND (os = 'common' OR os = ?2)
             ORDER BY rowid",
        )?;
        let mapped = stmt.query_map(params![command, target_os.as_str()], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
            ))
        })?;

        for row in mapped {
            if data.examples.len() >= max_examples {
                break;
            }

            let (desc, ex_desc, ex_cmd) = row?;
            if seen.insert((ex_desc.clone(), ex_cmd.clone())) {
                if data.description.is_empty() {
                    data.description = desc;
                }
                data.examples.push((ex_desc, ex_cmd));
                added += 1;
            }
        }
    }

    Ok(added)
}

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::Connection;

    // --- get_target_os ---

    #[test]
    fn test_explicit_linux_flag() {
        assert_eq!(get_target_os(true, false, false), TargetOs::Linux);
    }

    #[test]
    fn test_explicit_osx_flag() {
        assert_eq!(get_target_os(false, true, false), TargetOs::Osx);
    }

    #[test]
    fn test_explicit_windows_flag() {
        assert_eq!(get_target_os(false, false, true), TargetOs::Windows);
    }

    #[test]
    fn test_linux_takes_priority_over_osx() {
        assert_eq!(get_target_os(true, true, false), TargetOs::Linux);
    }

    // --- adjust_score ---

    #[test]
    fn test_filters_out_high_distance() {
        assert!(adjust_score("dummy query", "ls", "list files", 1.50).is_none());
        assert!(adjust_score("dummy query", "ls", "list files", 1.11).is_none());
    }

    #[test]
    fn test_accepts_low_distance() {
        assert!(adjust_score("dummy query", "ls", "list files", 0.5).is_some());
    }

    #[test]
    fn test_core_command_boosted() {
        let (ls_score, _) = adjust_score("dummy query", "ls", "list files", 0.5).unwrap();
        // 'ls' is in CORE_COMMANDS -> boosted by 0.67x (lower distance)
        assert!((ls_score - 0.335).abs() < 0.001);
    }

    #[test]
    fn test_grep_boosted() {
        let (grep_score, _) = adjust_score("dummy query", "grep", "search patterns", 0.5).unwrap();
        // 'grep' is in CORE_COMMANDS -> boosted by 0.67x
        assert!((grep_score - 0.335).abs() < 0.001);
    }

    #[test]
    fn test_niche_variant_penalized() {
        let (zgrep_score, _) =
            adjust_score("dummy query", "zgrep", "search compressed", 0.5).unwrap();
        // starts with 'z' AND ends with "grep" AND not "grep" -> penalized by 1.33x
        assert!((zgrep_score - 0.665).abs() < 0.001);
    }

    #[test]
    fn test_hyphenated_command_penalized() {
        let (score, _) = adjust_score("dummy query", "docker-cp", "copy files", 0.5).unwrap();
        assert!((score - 0.665).abs() < 0.001);
    }

    #[test]
    fn test_official_site_boosts_score() {
        let (plain, _) = adjust_score("dummy query", "find", "find files", 0.5).unwrap();
        let (official, _) = adjust_score(
            "dummy query",
            "find",
            "find files. More information: gnu.org",
            0.5,
        )
        .unwrap();
        assert!(official < plain); // lower distance is better
    }

    #[test]
    fn test_normal_command_no_modifier() {
        // 'randomtool' is not in CORE_COMMANDS, no special prefix/suffix -> no boost/penalty
        let (score, _) = adjust_score("dummy query", "randomtool", "transfer data", 0.5).unwrap();
        assert!((score - 0.5).abs() < 0.001);
    }

    #[test]
    fn test_exact_match_query() {
        // if user types "tar file", 'tar' gets a 0.5x exact match boost AND 0.67x core boost
        let (score, _) = adjust_score("tar file", "tar", "archive utility", 0.5).unwrap();
        assert!((score - (0.5 * 0.5 * 0.67)).abs() < 0.001);
    }

    fn test_conn() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute(
            "CREATE TABLE pages_vec (
                command TEXT,
                os TEXT,
                description TEXT,
                example_desc TEXT,
                example_cmd TEXT
            )",
            [],
        )
        .unwrap();
        conn
    }

    #[test]
    fn hydrate_adds_examples_for_thin_top_result() {
        let conn = test_conn();
        conn.execute(
            "INSERT INTO pages_vec(command, os, description, example_desc, example_cmd)
             VALUES
             ('ssh', 'common', 'Secure shell.', 'Dynamic forward', 'ssh -D 1080 user@host'),
             ('ssh', 'common', 'Secure shell.', 'Local forward', 'ssh -L 9999:example.org:80 user@host'),
             ('ssh', 'common', 'Secure shell.', 'No shell tunnel', 'ssh -L 9999:example.org:80 -N -T user@host')",
            [],
        )
        .unwrap();

        let mut sorted = vec![(
            "ssh".to_string(),
            CmdData {
                description: "Secure shell.".to_string(),
                platform: "common".to_string(),
                examples: vec![(
                    "Dynamic forward".to_string(),
                    "ssh -D 1080 user@host".to_string(),
                )],
                adjusted_score: 0.1,
                raw_distance: 0.1,
                heuristics: vec![],
            },
        )];

        let added = hydrate_top_result_examples(
            &conn,
            &mut sorted,
            "ssh local port forwarding",
            TargetOs::Linux,
            true,
            HYDRATE_MIN_EXAMPLES,
            HYDRATE_MAX_EXAMPLES,
        )
        .unwrap();

        assert_eq!(added, 2);
        assert_eq!(sorted[0].1.examples.len(), 3);
    }

    #[test]
    fn hydrate_respects_target_os_when_not_cross_platform() {
        let conn = test_conn();
        conn.execute(
            "INSERT INTO pages_vec(command, os, description, example_desc, example_cmd)
             VALUES
             ('tool', 'common', 'desc', 'Common example', 'tool --common'),
             ('tool', 'linux', 'desc', 'Linux example', 'tool --linux'),
             ('tool', 'osx', 'desc', 'OSX example', 'tool --osx')",
            [],
        )
        .unwrap();

        let mut sorted = vec![(
            "tool".to_string(),
            CmdData {
                description: "desc".to_string(),
                platform: "common".to_string(),
                examples: vec![("Common example".to_string(), "tool --common".to_string())],
                adjusted_score: 0.1,
                raw_distance: 0.1,
                heuristics: vec![],
            },
        )];

        let added = hydrate_top_result_examples(
            &conn,
            &mut sorted,
            "tool setup command",
            TargetOs::Linux,
            false,
            HYDRATE_MIN_EXAMPLES,
            HYDRATE_MAX_EXAMPLES,
        )
        .unwrap();

        let syntaxes: Vec<&str> = sorted[0]
            .1
            .examples
            .iter()
            .map(|(_, cmd)| cmd.as_str())
            .collect();

        assert_eq!(added, 1);
        assert!(syntaxes.contains(&"tool --common"));
        assert!(syntaxes.contains(&"tool --linux"));
        assert!(!syntaxes.contains(&"tool --osx"));
    }

    #[test]
    fn hydrate_skips_when_query_does_not_reference_command_family() {
        let conn = test_conn();
        conn.execute(
            "INSERT INTO pages_vec(command, os, description, example_desc, example_cmd)
             VALUES
             ('dnsrecon', 'linux', 'desc', 'Example 1', 'dnsrecon --help'),
             ('dnsrecon', 'linux', 'desc', 'Example 2', 'dnsrecon -d example.com')",
            [],
        )
        .unwrap();

        let mut sorted = vec![(
            "dnsrecon".to_string(),
            CmdData {
                description: "desc".to_string(),
                platform: "linux".to_string(),
                examples: vec![("Example 1".to_string(), "dnsrecon --help".to_string())],
                adjusted_score: 0.1,
                raw_distance: 0.1,
                heuristics: vec![],
            },
        )];

        let added = hydrate_top_result_examples(
            &conn,
            &mut sorted,
            "flush dns cache",
            TargetOs::Linux,
            true,
            HYDRATE_MIN_EXAMPLES,
            HYDRATE_MAX_EXAMPLES,
        )
        .unwrap();

        assert_eq!(added, 0);
        assert_eq!(sorted[0].1.examples.len(), 1);
    }

    #[test]
    fn hydrate_skips_for_complex_multi_intent_queries() {
        let conn = test_conn();
        conn.execute(
            "INSERT INTO pages_vec(command, os, description, example_desc, example_cmd)
             VALUES
             ('awk', 'common', 'desc', 'Example 1', 'awk --help'),
             ('awk', 'common', 'desc', 'Example 2', 'awk \"{print $1}\" file'),
             ('awk', 'common', 'desc', 'Example 3', 'awk \"{print $2}\" file')",
            [],
        )
        .unwrap();

        let mut sorted = vec![(
            "awk".to_string(),
            CmdData {
                description: "desc".to_string(),
                platform: "common".to_string(),
                examples: vec![("Example 1".to_string(), "awk --help".to_string())],
                adjusted_score: 0.1,
                raw_distance: 0.1,
                heuristics: vec![],
            },
        )];

        let added = hydrate_top_result_examples(
            &conn,
            &mut sorted,
            "awk parse csv and sum column",
            TargetOs::Linux,
            true,
            HYDRATE_MIN_EXAMPLES,
            HYDRATE_MAX_EXAMPLES,
        )
        .unwrap();

        assert_eq!(added, 0);
        assert_eq!(sorted[0].1.examples.len(), 1);
    }

    #[test]
    fn intent_coverage_detects_missing_sub_intent_terms() {
        let data = CmdData {
            description: "Run ad-hoc ansible commands.".to_string(),
            platform: "common".to_string(),
            examples: vec![(
                "Run command on group".to_string(),
                "ansible group -m command -a 'uptime'".to_string(),
            )],
            adjusted_score: 0.1,
            raw_distance: 0.1,
            heuristics: vec![],
        };

        let coverage = evaluate_intent_coverage("run ansible playbook with tags", "ansible", &data);
        assert!(coverage.score < 0.60);
        assert!(!coverage.strong);
        assert!(coverage.missing_terms.contains(&"playbook".to_string()));
        assert!(coverage.missing_terms.contains(&"tags".to_string()));
    }

    #[test]
    fn intent_coverage_passes_for_specific_match() {
        let data = CmdData {
            description: "Run playbooks.".to_string(),
            platform: "common".to_string(),
            examples: vec![(
                "Run with tags".to_string(),
                "ansible-playbook site.yml --tags web".to_string(),
            )],
            adjusted_score: 0.1,
            raw_distance: 0.1,
            heuristics: vec![],
        };

        let coverage =
            evaluate_intent_coverage("run ansible playbook with tags", "ansible-playbook", &data);
        assert!(coverage.score >= 0.60);
        assert!(coverage.strong);
    }
}
