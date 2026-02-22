use rusqlite::Connection;
use rusqlite::params;
use std::collections::HashMap;
use std::collections::hash_map::Entry;
use zerocopy::IntoBytes;

// (description, [(example_desc, example_cmd)], adjusted_score)
pub type CmdData = (String, Vec<(String, String)>, f64);
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

/// Distance threshold: prevents completely unrelated matches
const MAX_DISTANCE: f64 = 1.10;

pub fn get_target_os(linux: bool, osx: bool, windows: bool) -> &'static str {
    if linux {
        "linux"
    } else if osx {
        "osx"
    } else if windows {
        "windows"
    } else {
        match std::env::consts::OS {
            "macos" => "osx",
            "windows" => "windows",
            _ => "linux",
        }
    }
}

/// Pure scoring function: adjusts raw distance based on command name and description heuristics.
/// Returns `None` if the result should be filtered out (score above threshold).
pub fn adjust_score(cmd: &str, desc: &str, raw_distance: f64) -> Option<f64> {
    if raw_distance > MAX_DISTANCE {
        return None;
    }

    let is_official = OFFICIAL_SITES.iter().any(|&site| desc.contains(site));
    let mut score = if is_official {
        raw_distance * 0.8
    } else {
        raw_distance
    };

    // Heuristic to prefer basic unix commands over niche variants
    if cmd == "grep" || (cmd.len() <= 3 && !cmd.starts_with('q') && !cmd.starts_with('z')) {
        score *= 0.67; // Boost core commands like 'mv', 'cp', 'rm', 'grep'
    } else if cmd.contains('-')
        || cmd.starts_with('q')
        || cmd.starts_with('z')
        || (cmd.ends_with("grep") && cmd != "grep")
        || cmd.ends_with("all")
    {
        score *= 1.33; // Penalize niche variants
    }

    Some(score)
}

pub fn perform_search(
    conn: &Connection,
    q_vec: &[f32],
    target_os: &str,
) -> anyhow::Result<Vec<(String, CmdData)>> {
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

    for result in results {
        let (cmd, desc, ex_desc, ex_cmd, score) = result?;

        let adjusted_score = match adjust_score(&cmd, &desc, score) {
            Some(s) => s,
            None => continue,
        };

        match command_map.entry(cmd.clone()) {
            Entry::Vacant(e) => {
                e.insert((desc, vec![(ex_desc, ex_cmd)], adjusted_score));
            }
            Entry::Occupied(mut o) => {
                o.get_mut().1.push((ex_desc, ex_cmd));
            }
        }
    }

    let mut sorted: Vec<(String, CmdData)> = command_map.into_iter().collect();
    sorted.sort_by(|a, b| {
        b.1.2
            .partial_cmp(&a.1.2)
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
        assert_eq!(get_target_os(true, false, false), "linux");
    }

    #[test]
    fn test_explicit_osx_flag() {
        assert_eq!(get_target_os(false, true, false), "osx");
    }

    #[test]
    fn test_explicit_windows_flag() {
        assert_eq!(get_target_os(false, false, true), "windows");
    }

    #[test]
    fn test_linux_takes_priority_over_osx() {
        assert_eq!(get_target_os(true, true, false), "linux");
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
        let ls_score = adjust_score("ls", "list files", 0.5).unwrap();
        // 'ls' is <= 3 chars, not q/z prefix -> boosted by 0.67x (lower distance)
        assert!((ls_score - 0.335).abs() < 0.001);
    }

    #[test]
    fn test_grep_boosted() {
        let grep_score = adjust_score("grep", "search patterns", 0.5).unwrap();
        assert!((grep_score - 0.335).abs() < 0.001);
    }

    #[test]
    fn test_niche_variant_penalized() {
        let zgrep_score = adjust_score("zgrep", "search compressed", 0.5).unwrap();
        // starts with 'z' AND ends with "grep" -> penalized by 1.33x
        assert!((zgrep_score - 0.665).abs() < 0.001);
    }

    #[test]
    fn test_hyphenated_command_penalized() {
        let score = adjust_score("docker-cp", "copy files", 0.5).unwrap();
        assert!((score - 0.665).abs() < 0.001);
    }

    #[test]
    fn test_official_site_boosts_score() {
        let plain = adjust_score("find", "find files", 0.5).unwrap();
        let official = adjust_score("find", "find files. More information: gnu.org", 0.5).unwrap();
        assert!(official < plain); // lower distance is better
    }

    #[test]
    fn test_normal_command_no_modifier() {
        // 'curl' is 4 chars, no special prefix/suffix -> no boost or penalty
        let score = adjust_score("curl", "transfer data", 0.5).unwrap();
        assert!((score - 0.5).abs() < 0.001);
    }
}
