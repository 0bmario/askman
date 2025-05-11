use anyhow::Result;
use bytemuck;
use clap::Parser;
use colored::*;
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use rusqlite::ffi::sqlite3_auto_extension;
use rusqlite::{Connection,params};
use sqlite_vec::sqlite3_vec_init;

/// askman – offline CLI helper
#[derive(Parser, Debug)]
#[command(
    version,
    about = "Ask natural language questions about Unix/Linux commands."
)]
struct Args {
    #[arg(required = true)]
    question: Vec<String>,
}

fn main() -> Result<()> {
    // init sqlite vector extension
    unsafe {
        sqlite3_auto_extension(Some(std::mem::transmute(sqlite3_vec_init as *const ())));
    }

    // parse args and prepare query
    let args = Args::parse();
    let query = args.question.join(" ");

    // init db connection
    let conn = Connection::open("commands.db")?;
    ensure_fts_table_exists(&conn)?;

    // try semantic search first
    let found = try_semantic_search(&conn, &query)?;

    // fallback to keyword search only if semantic search failed
    if !found {
        try_keyword_search(&conn, &query)?;
    }

    Ok(())
}

/// create fts table if it doesn't exist
/// used for keyword search
fn ensure_fts_table_exists(conn: &Connection) -> Result<()> {
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            command,
            description,
            example_desc,
            example_cmd
        )",
        [],
    )?;

    // ensure fts table is populated
    conn.execute(
        "INSERT OR IGNORE INTO pages_fts
         SELECT command, description, example_desc, example_cmd
         FROM pages_vec",
        [],
    )?;

    Ok(())
}

fn try_semantic_search(conn: &Connection, query: &str) -> Result<bool> {
    let embedder = TextEmbedding::try_new(InitOptions::new(EmbeddingModel::AllMiniLML6V2))?;

    let formatted_query = format!("command: . description: . example: {}", query);
    let q_vec = embedder.embed(vec![formatted_query], None)?[0].clone();
    let q_blob: &[u8] = bytemuck::cast_slice(&q_vec);

    // find best matching using vector similarity
    // uses match from sqlite vector extension
    let mut stmt = conn.prepare(
        "SELECT command, description, example_desc, example_cmd, distance
         FROM pages_vec
         WHERE embedding MATCH ?1
         ORDER BY distance
         LIMIT 1;",
    )?;

    let result = stmt.query_row(params![q_blob], |row| {
        Ok((
            row.get::<_, String>(0)?, // command
            row.get::<_, String>(1)?, // description
            row.get::<_, String>(2)?, // example_desc
            row.get::<_, String>(3)?, // example_cmd
            row.get::<_, f64>(4)?,    // distance (score)
        ))
    });

    match result {
        Ok((cmd, desc, ex_desc, ex_cmd, score)) => {
            if score < 0.8 {
                print_answer(&cmd, &desc, &ex_desc, &ex_cmd);
                Ok(true)
            } else {
                Ok(false)
            }
        }
        Err(rusqlite::Error::QueryReturnedNoRows) => {
            println!("No semantic matches found.");
            Ok(false)
        }
        Err(e) => Err(e.into()),
    }
}

fn try_keyword_search(_conn: &Connection, _query: &str) -> Result<()> {
    todo!("to be implemented");
}

fn print_answer(cmd: &str, desc: &str, ex_desc: &str, ex_cmd: &str) {
    println!("{}", cmd.bold().green());
    println!("{}", desc);
    print!("\n{} ", "Example".green());
    print!("{}", ex_desc);
    println!("\n  {}", ex_cmd.cyan());
}

// fn print_example(ex_desc: &str, ex_cmd: &str) {
//     print!("\n{} ", "Example".green());
//     print!("{}", ex_desc);
//     println!("\n  {}", ex_cmd.cyan());
// }
