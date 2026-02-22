use rusqlite::Connection;
use rusqlite::params;
use std::collections::HashMap;
use std::collections::hash_map::Entry;
use zerocopy::IntoBytes;

// (description, [(example_desc, example_cmd)], adjusted_score)
pub type CmdData = (String, Vec<(String, String)>, f64);
pub type CmdMap = HashMap<String, CmdData>;

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
            _ => "linux", // Defaults freebsd/openbsd/linux to linux
        }
    }
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

        // Distance threshold: prevents completely unrelated matches
        if score > 1.10 {
            continue;
        }

        let is_official = official_sites.iter().any(|&site| desc.contains(site));
        let mut adjusted_score = if is_official { score * 1.2 } else { score };

        // Heuristic to prefer basic unix commands over niche variants
        if cmd == "grep" || (cmd.len() <= 3 && !cmd.starts_with('q') && !cmd.starts_with('z')) {
            adjusted_score *= 1.50; // Boost core commands like 'mv', 'cp', 'rm', 'grep'
        } else if cmd.contains('-')
            || cmd.starts_with('q')
            || cmd.starts_with('z')
            || (cmd.ends_with("grep") && cmd != "grep")
            || cmd.ends_with("all")
        {
            adjusted_score *= 0.75; // Penalize niche variants
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

    let mut sorted: Vec<(String, CmdData)> = command_map.into_iter().collect();
    sorted.sort_by(|a, b| {
        b.1.2
            .partial_cmp(&a.1.2)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    Ok(sorted)
}
