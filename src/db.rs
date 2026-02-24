use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::Connection;
use std::io::Write;
use std::path::{Path, PathBuf};

/// Returns the app data directory path WITHOUT creating it.
/// Use this when you only need the path (e.g. --clean).
pub fn get_app_dir_path() -> PathBuf {
    let mut path = dirs::data_dir().unwrap_or_else(|| PathBuf::from("."));
    path.push("askman");
    path
}

/// Global data directory: ~/.local/share/askman (linux) or ~/Library/Application Support/askman (mac)
/// Creates the directory if it doesn't exist.
pub fn get_app_dir() -> Result<PathBuf> {
    let path = get_app_dir_path();
    if !path.exists() {
        std::fs::create_dir_all(&path)?;
    }
    Ok(path)
}

/// Resolves commands.db path. Falls back to downloading from GitHub on first run.
pub fn get_db_path(app_dir: &Path) -> Result<PathBuf> {
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

    if global_db_path.exists() {
        ensure_valid_schema(&global_db_path)?;
    }

    if !global_db_path.exists() {
        println!("Downloading initial commands database (this only happens once)...");

        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(120))
            .build()?;

        let mut response = client
            .get("https://github.com/0bmario/askman/releases/latest/download/commands.db")
            .send()?
            .error_for_status()?;

        let total_size = response.content_length().unwrap_or(0);

        let pb = ProgressBar::new(total_size);
        pb.set_style(ProgressStyle::default_bar()
            .template("{spinner:.green} [{elapsed_precise}] [{wide_bar:.cyan/blue}] {bytes}/{total_bytes} ({bytes_per_sec}, {eta})")
            .unwrap()
            .progress_chars("#>-"));

        let tmp_db_path = global_db_path.with_extension("db.tmp");
        let result: Result<(), anyhow::Error> = {
            use std::io::Read;

            // Scoped so file handle is always dropped before rename/remove.
            let mut file = std::fs::File::create(&tmp_db_path)?;
            let mut downloaded: u64 = 0;
            let mut buffer = [0; 8192];

            (|| {
                loop {
                    let bytes_read = response.read(&mut buffer)?;
                    if bytes_read == 0 {
                        break;
                    }
                    file.write_all(&buffer[..bytes_read])?;
                    downloaded += bytes_read as u64;
                    pb.set_position(downloaded);
                }
                Ok(())
            })()
        }; // file handle is dropped here, before rename or remove_file

        if result.is_ok() {
            std::fs::rename(&tmp_db_path, &global_db_path)?;
            pb.finish_with_message("Download complete.");
        } else {
            let _ = std::fs::remove_file(&tmp_db_path);
            result?;
        }
    }

    Ok(global_db_path)
}

pub fn get_connection(db_path: &Path) -> Result<Connection> {
    Ok(Connection::open(db_path)?)
}

/// Checks if the database has the required schema (must have the `os` metadata column).
/// If it's an old v1 schema (missing `os`), it actively removes it so it can be rebuilt.
pub fn ensure_valid_schema(db_path: &Path) -> Result<()> {
    if !db_path.exists() {
        return Ok(());
    }

    let has_os_column = {
        let conn = get_connection(db_path)?;
        let mut stmt = conn.prepare("PRAGMA table_info(pages_vec)")?;
        let mut rows = stmt.query([])?;
        let mut found = false;
        while let Some(row) = rows.next()? {
            let name: String = row.get(1)?;
            if name == "os" {
                found = true;
                break;
            }
        }
        found
    };

    if !has_os_column {
        println!(
            "Detected legacy database schema (v1, missing OS flags). Removing to allow upgrade..."
        );
        std::fs::remove_file(db_path)?;
    }

    Ok(())
}
