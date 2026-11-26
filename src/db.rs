use anyhow::{Result, bail};
use indicatif::{ProgressBar, ProgressStyle};
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use std::io::Write;

// The database is published under its own release tag so app releases never
// change which data a binary downloads. Bump all three values together: a new
// file name per pinned database is what makes existing installs download it,
// because a database is only downloaded when its file is missing.
pub const DB_FILE: &str = "commands-v2.db";
const DB_URL: &str = "https://github.com/0bmario/askman/releases/download/db-v2/commands-v2.db";
const DB_SHA256: &str = "ae7a09479bdb25b06b1054a6c92b3505899945b51f6efc2c9e5e28854df2d93e";
/// Download temp files are named `<DB_FILE>.tmp-<pid>`.
const TMP_INFIX: &str = ".tmp-";
/// A temp file untouched this long belongs to a download that was killed.
const STALE_TMP_AGE: Duration = Duration::from_secs(10 * 60);
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};

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

/// Resolves the pinned database path. Falls back to downloading from GitHub on first run.
pub fn get_db_path(app_dir: &Path) -> Result<PathBuf> {
    // Check next to executable first (backward compat for local dev installs)
    if let Ok(exe_path) = std::env::current_exe()
        && let Some(dir) = exe_path.parent()
    {
        let local_db_path = dir.join(DB_FILE);
        if local_db_path.exists() {
            return Ok(local_db_path);
        }
    }

    let global_db_path = app_dir.join(DB_FILE);

    if global_db_path.exists() {
        ensure_valid_schema(&global_db_path)?;
    }

    if !global_db_path.exists() {
        eprintln!("Downloading initial commands database (this only happens once)...");

        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(120))
            .build()?;

        let response = client.get(DB_URL).send()?.error_for_status()?;

        let total_size = response.content_length().unwrap_or(0);

        let pb = ProgressBar::new(total_size);
        pb.set_style(ProgressStyle::default_bar()
            .template("{spinner:.green} [{elapsed_precise}] [{wide_bar:.cyan/blue}] {bytes}/{total_bytes} ({bytes_per_sec}, {eta})")
            .unwrap()
            .progress_chars("#>-"));

        remove_stale_tmp_files(app_dir);
        install_download(response, app_dir, &global_db_path, &pb)?;
        pb.finish_with_message("Download complete.");
    }

    Ok(global_db_path)
}

/// Writes the download to a per-process temp file and renames it into place once its
/// SHA-256 matches, so concurrent first runs never share or rename each other's temp file.
fn install_download(
    mut body: impl std::io::Read,
    app_dir: &Path,
    db_path: &Path,
    pb: &ProgressBar,
) -> Result<()> {
    let tmp_db_path = app_dir.join(format!("{DB_FILE}{TMP_INFIX}{}", std::process::id()));
    let result: Result<(), anyhow::Error> = {
        // Scoped so file handle is always dropped before rename/remove.
        let mut file = std::fs::File::create(&tmp_db_path)?;
        let mut downloaded: u64 = 0;
        let mut buffer = [0; 8192];
        let mut hasher = Sha256::new();

        (|| {
            loop {
                let bytes_read = body.read(&mut buffer)?;
                if bytes_read == 0 {
                    break;
                }
                file.write_all(&buffer[..bytes_read])?;
                hasher.update(&buffer[..bytes_read]);
                downloaded += bytes_read as u64;
                pb.set_position(downloaded);
            }
            verify_sha256(&format!("{:x}", hasher.finalize()))
        })()
    }; // file handle is dropped here, before rename or remove_file

    if let Err(error) = result {
        let _ = std::fs::remove_file(&tmp_db_path);
        return Err(error);
    }
    move_into_place(&tmp_db_path, db_path)
}

/// Renames the verified temp file to the database path. If that fails but the database now
/// exists, another run installed its own verified copy (and may have swept our temp file as
/// stale after a sleep or clock jump), so the database is ready.
fn move_into_place(tmp_db_path: &Path, db_path: &Path) -> Result<()> {
    let Err(error) = std::fs::rename(tmp_db_path, db_path) else {
        return Ok(());
    };
    let _ = std::fs::remove_file(tmp_db_path);
    if db_path.exists() {
        return Ok(());
    }
    Err(error.into())
}

/// Removes temp files left by killed downloads (about 60 MB each). A live download writes
/// at least every 120 s (the client's read timeout), so a file untouched for longer than
/// the limit belongs to a dead run. Best effort: a failure here must not stop the download.
fn remove_stale_tmp_files(app_dir: &Path) {
    let Ok(entries) = std::fs::read_dir(app_dir) else {
        return;
    };
    // Also matches `<DB_FILE>.tmp`, the shared name 0.3.11 and older used.
    let tmp_prefix = format!("{DB_FILE}.tmp");
    for entry in entries.flatten() {
        let is_our_tmp = entry.file_name().to_string_lossy().starts_with(&tmp_prefix);
        let age = entry
            .metadata()
            .and_then(|metadata| metadata.modified())
            .ok()
            .and_then(|modified| SystemTime::now().duration_since(modified).ok());
        if is_our_tmp && age.is_some_and(|age| age > STALE_TMP_AGE) {
            let _ = std::fs::remove_file(entry.path());
        }
    }
}

type SqliteExtensionEntryPoint = unsafe extern "C" fn(
    *mut rusqlite::ffi::sqlite3,
    *mut *mut std::os::raw::c_char,
    *const rusqlite::ffi::sqlite3_api_routines,
) -> std::os::raw::c_int;

/// Registers sqlite-vec for every connection opened afterwards.
pub fn register_sqlite_vec() {
    // sqlite-vec exposes its entry point without the argument types SQLite expects.
    unsafe {
        rusqlite::ffi::sqlite3_auto_extension(Some(std::mem::transmute::<
            *const (),
            SqliteExtensionEntryPoint,
        >(
            sqlite_vec::sqlite3_vec_init as *const ()
        )));
    }
}

fn verify_sha256(actual: &str) -> Result<()> {
    if actual != DB_SHA256 {
        bail!("downloaded commands database has SHA-256 {actual}, expected {DB_SHA256}");
    }
    Ok(())
}

/// Lets SQLite map the database into memory (up to this many bytes) instead of reading it
/// page by page through its small page cache.
const MMAP_SIZE: i64 = 256 * 1024 * 1024;

pub fn get_connection(db_path: &Path) -> Result<Connection> {
    let conn = Connection::open(db_path)?;
    // The KNN scan reads every stored vector (about 46 MB) on each query; through the map it
    // skips copying them, about 4 of its 14 ms. The data and every distance stay the same.
    conn.pragma_update(None, "mmap_size", MMAP_SIZE)?;
    Ok(conn)
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
        eprintln!(
            "Detected legacy database schema (v1, missing OS flags). Removing to allow upgrade..."
        );
        std::fs::remove_file(db_path)?;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verify_sha256_rejects_a_different_digest() {
        assert!(verify_sha256(DB_SHA256).is_ok());
        let error = verify_sha256(&"0".repeat(64)).unwrap_err();
        assert!(error.to_string().contains("expected"), "{error}");
    }

    fn scratch_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("askman-db-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn a_mismatched_download_leaves_no_files() {
        let dir = scratch_dir("mismatch");
        let db_path = dir.join(DB_FILE);
        let error = install_download(
            &b"not the database"[..],
            &dir,
            &db_path,
            &ProgressBar::hidden(),
        )
        .unwrap_err();
        assert!(error.to_string().contains("expected"), "{error}");
        assert_eq!(std::fs::read_dir(&dir).unwrap().count(), 0);
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn a_failed_rename_is_fine_once_another_run_installed_the_database() {
        let dir = scratch_dir("rename");
        let tmp_db_path = dir.join(format!("{DB_FILE}.tmp-111"));
        let db_path = dir.join(DB_FILE);

        assert!(move_into_place(&tmp_db_path, &db_path).is_err());

        std::fs::File::create(&db_path).unwrap();
        assert!(move_into_place(&tmp_db_path, &db_path).is_ok());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn only_old_download_temp_files_are_removed() {
        let dir = scratch_dir("stale");
        let old = SystemTime::now() - STALE_TMP_AGE - Duration::from_secs(60);
        let touch = |name: &str, modified: SystemTime| {
            let file = std::fs::File::create(dir.join(name)).unwrap();
            file.set_modified(modified).unwrap();
        };
        touch(&format!("{DB_FILE}.tmp-111"), old);
        touch(&format!("{DB_FILE}.tmp-222"), SystemTime::now());
        touch(&format!("{DB_FILE}.tmp"), old);
        touch(DB_FILE, old);
        touch("commands-v1.db.tmp-333", old);

        remove_stale_tmp_files(&dir);

        let mut left: Vec<String> = std::fs::read_dir(&dir)
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        left.sort();
        let expected = [
            "commands-v1.db.tmp-333".to_string(),
            DB_FILE.to_string(),
            format!("{DB_FILE}.tmp-222"),
        ];
        assert_eq!(left, expected);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
