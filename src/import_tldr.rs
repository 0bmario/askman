use anyhow::{Context, Result};
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use rusqlite::ffi::sqlite3_auto_extension;
use rusqlite::{Connection, params};
use sqlite_vec::sqlite3_vec_init;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use zerocopy::IntoBytes;

fn get_app_dir() -> std::path::PathBuf {
    let mut path = dirs::data_dir().unwrap_or_else(|| std::path::PathBuf::from("."));
    path.push("askman");
    if !path.exists() {
        std::fs::create_dir_all(&path).unwrap_or_default();
    }
    path
}

/// Downloads and extracts the tldr-pages repo zip into a temp directory.
/// Returns the path to the extracted `pages/` folder (e.g. /tmp/askman_tldr/tldr-main/pages).
fn download_tldr_pages() -> Result<PathBuf> {
    let tmp_dir = std::env::temp_dir().join("askman_tldr");
    if tmp_dir.exists() {
        fs::remove_dir_all(&tmp_dir)?;
    }
    fs::create_dir_all(&tmp_dir)?;

    println!("Downloading tldr-pages from GitHub...");
    let zip_url = "https://github.com/tldr-pages/tldr/archive/refs/heads/main.zip";
    let response = reqwest::blocking::get(zip_url)?;
    let bytes = response.bytes()?;

    // Write zip to disk, then extract (zip crate needs a seekable reader)
    let zip_path = tmp_dir.join("tldr.zip");
    let mut file = fs::File::create(&zip_path)?;
    file.write_all(&bytes)?;

    println!("Extracting...");
    let file = fs::File::open(&zip_path)?;
    let mut archive = zip::ZipArchive::new(file)?;
    archive.extract(&tmp_dir)?;

    // The zip extracts to `tldr-main/pages/`
    let pages_dir = tmp_dir.join("tldr-main").join("pages");
    if !pages_dir.exists() {
        return Err(anyhow::anyhow!(
            "Expected pages/ directory not found in zip"
        ));
    }

    Ok(pages_dir)
}

fn main() -> Result<()> {
    unsafe {
        sqlite3_auto_extension(Some(std::mem::transmute(sqlite3_vec_init as *const ())));
    }

    let app_dir = get_app_dir();

    // Auto-download tldr repo, extract to temp dir
    let pages_dir = download_tldr_pages()?;

    println!("Initializing embedding model...");
    let embed_options = InitOptions::new(EmbeddingModel::AllMiniLML6V2)
        .with_show_download_progress(true)
        .with_cache_dir(app_dir.join("models"));
    let model = TextEmbedding::try_new(embed_options)?;

    let db_path = app_dir.join("commands.db");
    let conn = Connection::open(&db_path).context("Failed to open database")?;

    conn.execute("DROP TABLE IF EXISTS pages_vec", [])?;

    // os column tags each command by platform for filtered queries
    conn.execute(
        "CREATE VIRTUAL TABLE pages_vec USING vec0(
            command TEXT,
            os TEXT,
            description TEXT,
            example_desc TEXT,
            example_cmd TEXT,
            embedding FLOAT[384]
        )",
        [],
    )?;

    let mut count = 0;
    for os_type in ["common", "linux", "osx", "windows"] {
        let dir = pages_dir.join(os_type);
        if dir.exists() {
            println!("Processing directory: {}", os_type);
            count += process_directory(&dir, os_type, &conn, &model)?;
        } else {
            println!("Directory {} not found. Skipping...", os_type);
        }
    }

    // Clean up temp directory
    let tmp_dir = std::env::temp_dir().join("askman_tldr");
    fs::remove_dir_all(&tmp_dir).ok();

    println!("\nImported {} examples from tldr pages", count);
    println!("Database saved to: {}", db_path.display());
    Ok(())
}

/// Reads all .md files in a tldr directory, embeds each example, and inserts into SQLite.
fn process_directory(
    dir_path: &Path,
    os_tag: &str,
    conn: &Connection,
    model: &TextEmbedding,
) -> Result<usize> {
    let entries = fs::read_dir(dir_path)
        .with_context(|| format!("Failed to read directory: {}", dir_path.display()))?;

    let mut count = 0;

    for entry in entries {
        let entry = entry?;
        let path = entry.path();

        if path.extension().and_then(|s| s.to_str()) != Some("md") {
            continue;
        }

        let content = fs::read_to_string(&path)
            .with_context(|| format!("Failed to read file: {}", path.display()))?;

        // parse tldr page
        let (command, description, examples) = parse_tldr(&content, &path);

        for example in examples.split("\n\n") {
            let lines: Vec<&str> = example.lines().collect();
            if lines.len() < 2 {
                continue;
            }

            let example_desc = lines[0];
            let example_cmd = lines[1];

            // generate embedding for this specific example
            let embedding_text = format!(
                "Task: {}. Command: {}. Description: {}. Example: {} {}",
                example_desc, command, description, example_desc, example_cmd
            );

            let embeddings = model
                .embed(vec![embedding_text], None)
                .with_context(|| format!("Failed to create embedding for command: {}", command))?;

            let embedding_vec = &embeddings[0];
            let embedding_blob = embedding_vec.as_bytes();

            // insert using the vec0 table
            conn.execute(
                "INSERT INTO pages_vec(command, os, description, example_desc, example_cmd, embedding)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![
                    command,
                    os_tag,
                    description,
                    example_desc,
                    example_cmd,
                    embedding_blob
                ],
            )?;

            count += 1;
        }
    }

    Ok(count)
}

/// Parse a tldr page into a command, description, and examples
/// leverage the tldr-pages format:
// # command-name
// > Short, snappy description.
// > Preferably one line; two are acceptable if necessary.
// > More information: <https://url-to-upstream.tld>.
//
// - Example description:
// `command --option`
//
// - Example description:
// `command --option1 --option2 {{arg_value}}`
fn parse_tldr(md: &str, file: &Path) -> (String, String, String) {
    let name = file.file_stem().unwrap().to_string_lossy().into_owned();
    let mut desc_lines = Vec::new();
    let mut examples = String::new();
    let mut want_code = false;

    for line in md.lines().map(|l| l.trim()) {
        if line.is_empty() {
            continue;
        }

        match line.chars().next() {
            Some('>') => {
                // collect description lines
                let desc_line = line[1..].trim();
                // // skip urls
                // if !desc_line.starts_with('<') {
                //     desc_lines.push(desc_line);
                // }
                desc_lines.push(desc_line);
            }
            Some('-') => {
                examples.push_str(line[1..].trim());
                examples.push('\n');
                want_code = true;
            }
            Some('`') if want_code => {
                examples.push_str(line.trim_matches('`'));
                examples.push_str("\n\n");
                want_code = false;
            }
            _ => {}
        }
    }

    let description = desc_lines.join(" ");

    (name, description, examples.trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::Connection;
    use std::fs;

    // --- parse_tldr ---

    #[test]
    fn test_parse_standard_tldr_page() {
        let md = r#"# ls

> List directory contents.
> More information: <https://www.gnu.org/software/coreutils/ls>.

- List files one per line:

`ls -1`

- List all files, including hidden files:

`ls -a`
"#;
        let path = Path::new("ls.md");
        let (name, desc, examples) = parse_tldr(md, path);

        assert_eq!(name, "ls");
        assert!(desc.contains("List directory contents."));
        assert!(examples.contains("ls -1"));
        assert!(examples.contains("ls -a"));
    }

    #[test]
    fn test_parse_multi_line_description() {
        let md = r#"# tar

> Archiving utility.
> Often combined with a compression method, such as gzip or bzip2.
> More information: <https://www.gnu.org/software/tar>.

- Create an archive:

`tar cf {{target.tar}} {{file1}} {{file2}}`
"#;
        let path = Path::new("tar.md");
        let (name, desc, _examples) = parse_tldr(md, path);

        assert_eq!(name, "tar");
        assert!(desc.contains("Archiving utility."));
        assert!(desc.contains("Often combined"));
    }

    #[test]
    fn test_parse_preserves_variables() {
        let md = r#"# cp

> Copy files and directories.

- Copy a file to another location:

`cp {{path/to/source}} {{path/to/destination}}`
"#;
        let path = Path::new("cp.md");
        let (_, _, examples) = parse_tldr(md, path);

        assert!(examples.contains("{{path/to/source}}"));
        assert!(examples.contains("{{path/to/destination}}"));
    }

    #[test]
    fn test_parse_multiple_examples() {
        let md = r#"# chmod

> Change permissions.

- Give execute permission:

`chmod +x {{file}}`

- Set permissions to 755:

`chmod 755 {{file}}`

- Remove write permission:

`chmod -w {{file}}`
"#;
        let path = Path::new("chmod.md");
        let (_, _, examples) = parse_tldr(md, path);

        let example_blocks: Vec<&str> = examples.split("\n\n").filter(|s| !s.is_empty()).collect();
        assert_eq!(example_blocks.len(), 3);
    }

    #[test]
    fn test_parse_empty_content() {
        let md = "# empty\n";
        let path = Path::new("empty.md");
        let (name, desc, examples) = parse_tldr(md, path);

        assert_eq!(name, "empty");
        assert!(desc.is_empty());
        assert!(examples.is_empty());
    }

    // --- database creation (existing test) ---

    #[test]
    fn test_database_creation() -> Result<()> {
        unsafe {
            sqlite3_auto_extension(Some(std::mem::transmute(sqlite3_vec_init as *const ())));
        }

        // test database
        let db_path = "test_commands.db";
        let conn = Connection::open(db_path)?;

        conn.execute("DROP TABLE IF EXISTS pages_vec", [])?;

        conn.execute(
            "CREATE VIRTUAL TABLE pages_vec USING vec0(
                command TEXT,
                os TEXT,
                description TEXT,
                example_desc TEXT,
                example_cmd TEXT,
                embedding FLOAT[384]
            )",
            [],
        )?;

        // test embedding model
        let model = TextEmbedding::try_new(
            InitOptions::new(EmbeddingModel::AllMiniLML6V2).with_show_download_progress(false),
        )?;

        let test_data = vec![
            (
                "test_cmd",
                "Test description",
                "Test example description",
                "test_cmd --example",
            ),
            (
                "another_cmd",
                "Another description",
                "Another example description",
                "another_cmd --test",
            ),
        ];

        for (cmd, desc, ex_desc, ex_cmd) in test_data {
            let embedding_text = format!(
                "command: {}. description: {}. example: {} {}",
                cmd, desc, ex_desc, ex_cmd
            );
            let embeddings = model.embed(vec![embedding_text], None)?;
            let embedding_vec = &embeddings[0];
            let embedding_blob = embedding_vec.as_bytes();

            conn.execute(
                "INSERT INTO pages_vec(command, os, description, example_desc, example_cmd, embedding)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![cmd, "common", desc, ex_desc, ex_cmd, embedding_blob],
            )?;
        }

        // test table structure
        let mut stmt =
            conn.prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='pages_vec'")?;
        let table_sql: String = stmt.query_row([], |row| row.get(0))?;
        assert!(table_sql.contains("USING vec0"));
        assert!(table_sql.contains("embedding FLOAT[384]"));

        // test data insertion
        let count: i64 = conn.query_row("SELECT COUNT(*) FROM pages_vec", [], |r| r.get(0))?;
        assert_eq!(count, 2);

        // test embedding format
        let mut stmt = conn.prepare("SELECT length(embedding) FROM pages_vec LIMIT 1")?;
        let embedding_size: i64 = stmt.query_row([], |r| r.get(0))?;
        assert_eq!(embedding_size, 1536); // 384 * 4 bytes for float32

        // test vector similarity search
        let mut stmt =
            conn.prepare("SELECT embedding FROM pages_vec WHERE command = 'test_cmd'")?;
        let test_embedding: Vec<u8> = stmt.query_row([], |row| row.get(0))?;

        let mut stmt = conn.prepare(
            "SELECT command, distance
             FROM pages_vec
             WHERE embedding MATCH ?
             ORDER BY distance
             LIMIT 1",
        )?;

        let (matched_cmd, distance): (String, f64) = stmt
            .query_row(params![test_embedding], |row| {
                Ok((row.get(0)?, row.get(1)?))
            })?;

        assert_eq!(matched_cmd, "test_cmd");
        assert!(distance < 0.1); // close 0 for exact match

        fs::remove_file(db_path)?;

        Ok(())
    }
}
