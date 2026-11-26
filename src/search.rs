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

/// Cosine distance threshold (0 = identical, 2 = opposite): filters out unrelated matches.
/// sqlite-vec's vec0 table returns cosine distance by default via the `distance` column.
/// See: https://alexgarcia.xyz/sqlite-vec/api-reference.html#vec_distance_cosine
const MAX_DISTANCE: f64 = 1.10;

/// Score multiplier for pages tagged with the target OS, so they beat near-tied `common` pages.
const TARGET_OS_FACTOR: f64 = 0.9;

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

/// Pure scoring function: adjusts raw distance for the target OS.
/// Returns `None` if the result should be filtered out (score above threshold).
pub fn adjust_score(is_target_os: bool, raw_distance: f64) -> Option<(f64, Vec<String>)> {
    if raw_distance > MAX_DISTANCE {
        return None;
    }

    let mut applied_heuristics = Vec::new();
    let mut score = raw_distance;

    if is_target_os {
        applied_heuristics.push(format!("target_os ({TARGET_OS_FACTOR}x)"));
        score *= TARGET_OS_FACTOR;
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
        "SELECT command, os = ?2, description, example_desc, example_cmd, distance
         FROM pages_vec
         WHERE (os = 'common' OR os = ?2) AND embedding MATCH ?1
         ORDER BY distance
         LIMIT 7;",
    )?;

    let results = stmt.query_map(params![q_blob, target_os.as_str()], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, bool>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, f64>(5)?,
        ))
    })?;

    let mut command_map: CmdMap = HashMap::new();

    for result in results {
        let (cmd, is_target_os, desc, ex_desc, ex_cmd, raw_distance) = result?;

        let (adjusted_score, heuristics) = match adjust_score(is_target_os, raw_distance) {
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
        assert!(adjust_score(false, 1.50).is_none());
        assert!(adjust_score(false, 1.11).is_none());
    }

    #[test]
    fn test_accepts_low_distance() {
        assert!(adjust_score(false, 0.5).is_some());
    }

    #[test]
    fn test_target_os_page_boosted() {
        let (score, _) = adjust_score(true, 0.5).unwrap();
        assert!((score - 0.5 * TARGET_OS_FACTOR).abs() < 0.001);
    }

    #[test]
    fn test_other_page_keeps_raw_distance() {
        // Only the target OS changes the score; the command name plays no part.
        let (score, heuristics) = adjust_score(false, 0.5).unwrap();
        assert!((score - 0.5).abs() < 0.001);
        assert!(heuristics.is_empty());
    }
}
