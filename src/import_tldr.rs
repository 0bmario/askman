use anyhow::{Context, Result};
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use rusqlite::ffi::sqlite3_auto_extension;
use rusqlite::{Connection, params};
use sqlite_vec::sqlite3_vec_init;
use std::fs;
use std::path::Path;
use zerocopy::IntoBytes;

fn main() -> Result<()> {
    unsafe {
        sqlite3_auto_extension(Some(std::mem::transmute(sqlite3_vec_init as *const ())));
    }

    println!("Initializing embedding model...");
    let model = TextEmbedding::try_new(
        InitOptions::new(EmbeddingModel::AllMiniLML6V2).with_show_download_progress(true),
    )?;

    // init db
    let db_path = "commands.db";
    let conn = Connection::open(db_path).context("Failed to open database")?;

    // drop existing tables if they exist
    conn.execute("DROP TABLE IF EXISTS pages_vec", [])?;

    // create table
    conn.execute(
        "CREATE VIRTUAL TABLE pages_vec USING vec0(
            command TEXT,
            description TEXT,
            example_desc TEXT,
            example_cmd TEXT,
            embedding FLOAT[384]
        )",
        [],
    )?;

    // process all files in common folder
    let common_dir = "common";
    let entries = fs::read_dir(common_dir)
        .with_context(|| format!("Failed to read directory: {}", common_dir))?;

    let mut count = 0;

    for entry in entries {
        let entry = entry?;
        let path = entry.path();
        
        if path.extension().and_then(|s| s.to_str()) != Some("md") {
            continue;
        }
        
        println!("Processing file: {}", path.display());
        
        let content = fs::read_to_string(&path)
            .with_context(|| format!("Failed to read file: {}", path.display()))?;
        
        // parse tldr page
        let (command, description, examples) = parse_tldr(&content, &path);
        println!("Parsed command: {}", command);

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
            
            let embeddings = model.embed(vec![embedding_text], None)
                .with_context(|| format!("Failed to create embedding for command: {}", command))?;
            
            let embedding_vec = &embeddings[0];
            let embedding_blob = embedding_vec.as_bytes();

            // insert using the vec0 table
            conn.execute(
                "INSERT INTO pages_vec(command, description, example_desc, example_cmd, embedding)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
                params![
                    command,
                    description,
                    example_desc,
                    example_cmd,
                    embedding_blob
                ],
            )?;
            
            count += 1;
        }
    }

    println!("\nImported {} examples from tldr pages", count);
    Ok(())
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
                examples.push_str(&line[1..].trim());
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
                "INSERT INTO pages_vec(command, description, example_desc, example_cmd, embedding)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
                params![cmd, desc, ex_desc, ex_cmd, embedding_blob],
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
