use rusqlite::Connection;
use rusqlite::params;
use std::collections::HashMap;
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
    pub examples: Vec<(String, String)>,
    pub adjusted_score: f64,
    pub raw_distance: f64,
    pub heuristics: Vec<String>,
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

/// Cosine distance threshold (0 = identical, 2 = opposite): filters out unrelated matches.
/// sqlite-vec's vec0 table returns cosine distance by default via the `distance` column.
/// See: https://alexgarcia.xyz/sqlite-vec/api-reference.html#vec_distance_cosine
const MAX_DISTANCE: f64 = 1.10;

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
pub fn adjust_score(cmd: &str, desc: &str, raw_distance: f64) -> Option<(f64, Vec<String>)> {
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

    // Heuristic to prefer basic unix commands over niche variants
    if cmd == "grep" || (cmd.len() <= 3 && !cmd.starts_with('q') && !cmd.starts_with('z')) {
        applied_heuristics.push("core_command (0.67x)".to_string());
        score *= 0.67; // Boost core commands like 'mv', 'cp', 'rm', 'grep'
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
    q_vec: &[f32],
    target_os: TargetOs,
) -> anyhow::Result<Vec<(String, CmdData)>> {
    let q_blob = q_vec.as_bytes();

    let mut stmt = conn.prepare(
        "SELECT command, description, example_desc, example_cmd, distance
         FROM pages_vec
         WHERE (os = 'common' OR os = ?2) AND embedding MATCH ?1
         ORDER BY distance
         LIMIT 7;",
    )?;

    let results = stmt.query_map(params![q_blob, target_os.as_str()], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, f64>(4)?,
        ))
    })?;

    let mut command_map: CmdMap = HashMap::new();

    for result in results {
        let (cmd, desc, ex_desc, ex_cmd, raw_distance) = result?;

        let (adjusted_score, heuristics) = match adjust_score(&cmd, &desc, raw_distance) {
            Some(s) => s,
            None => {
                continue;
            }
        };

        match command_map.entry(cmd.clone()) {
            Entry::Vacant(e) => {
                e.insert(CmdData {
                    description: desc,
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

#[cfg(test)]
mod tests {
    use super::*;

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
        assert!(adjust_score("ls", "list files", 1.50).is_none());
        assert!(adjust_score("ls", "list files", 1.11).is_none());
    }

    #[test]
    fn test_accepts_low_distance() {
        assert!(adjust_score("ls", "list files", 0.5).is_some());
    }

    #[test]
    fn test_core_command_boosted() {
        let (ls_score, _) = adjust_score("ls", "list files", 0.5).unwrap();
        // 'ls' is <= 3 chars, not q/z prefix -> boosted by 0.67x (lower distance)
        assert!((ls_score - 0.335).abs() < 0.001);
    }

    #[test]
    fn test_grep_boosted() {
        let (grep_score, _) = adjust_score("grep", "search patterns", 0.5).unwrap();
        assert!((grep_score - 0.335).abs() < 0.001);
    }

    #[test]
    fn test_niche_variant_penalized() {
        let (zgrep_score, _) = adjust_score("zgrep", "search compressed", 0.5).unwrap();
        // starts with 'z' AND ends with "grep" -> penalized by 1.33x
        assert!((zgrep_score - 0.665).abs() < 0.001);
    }

    #[test]
    fn test_hyphenated_command_penalized() {
        let (score, _) = adjust_score("docker-cp", "copy files", 0.5).unwrap();
        assert!((score - 0.665).abs() < 0.001);
    }

    #[test]
    fn test_official_site_boosts_score() {
        let (plain, _) = adjust_score("find", "find files", 0.5).unwrap();
        let (official, _) =
            adjust_score("find", "find files. More information: gnu.org", 0.5).unwrap();
        assert!(official < plain); // lower distance is better
    }

    #[test]
    fn test_normal_command_no_modifier() {
        // 'curl' is 4 chars, no special prefix/suffix -> no boost or penalty
        let (score, _) = adjust_score("curl", "transfer data", 0.5).unwrap();
        assert!((score - 0.5).abs() < 0.001);
    }
}
