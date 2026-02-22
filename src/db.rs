use anyhow::Result;
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::Connection;
use std::io::Write;
use std::path::{Path, PathBuf};

/// Global data directory: ~/.local/share/askman (linux) or ~/Library/Application Support/askman (mac)
pub fn get_app_dir() -> Result<PathBuf> {
    let mut path = dirs::data_dir().unwrap_or_else(|| PathBuf::from("."));
    path.push("askman");
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

    if !global_db_path.exists() {
        println!("Downloading initial commands database (this only happens once)...");

        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .build()?;

        let mut response = client
            .get("https://raw.githubusercontent.com/0bmario/askman/main/commands.db")
            .send()?
            .error_for_status()?;

        let total_size = response.content_length().unwrap_or(0);

        let pb = ProgressBar::new(total_size);
        pb.set_style(ProgressStyle::default_bar()
            .template("{spinner:.green} [{elapsed_precise}] [{wide_bar:.cyan/blue}] {bytes}/{total_bytes} ({bytes_per_sec}, {eta})")
            .unwrap()
            .progress_chars("#>-"));

        let mut file = std::fs::File::create(&global_db_path)?;
        let mut downloaded: u64 = 0;
        let mut buffer = [0; 8192];

        use std::io::Read;
        loop {
            let bytes_read = response.read(&mut buffer)?;
            if bytes_read == 0 {
                break;
            }
            file.write_all(&buffer[..bytes_read])?;
            downloaded += bytes_read as u64;
            pb.set_position(downloaded);
        }

        pb.finish_with_message("Download complete.");
    }

    Ok(global_db_path)
}

pub fn get_connection(db_path: &Path) -> Result<Connection> {
    Ok(Connection::open(db_path)?)
}
