use anyhow::Result;
use clap::Parser;
use colored::*;
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use rusqlite::ffi::sqlite3_auto_extension;
use rusqlite::{Connection, params};
use sqlite_vec::sqlite3_vec_init;
use zerocopy::IntoBytes;

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

    // perform semantic search
    try_semantic_search(&conn, &query)?;

    Ok(())
}

fn try_semantic_search(conn: &Connection, query: &str) -> Result<()> {
    let embedder = TextEmbedding::try_new(InitOptions::new(EmbeddingModel::AllMiniLML6V2))?;

    let formatted_query = format!("command: . description: . example: {}", query);
    let q_vec = embedder.embed(vec![formatted_query], None)?[0].clone();
    let q_blob = q_vec.as_bytes();

    // find best matching using vector similarity
    let mut stmt = conn.prepare(
        "SELECT command, description, example_desc, example_cmd, distance
         FROM pages_vec
         WHERE embedding MATCH ?1
         ORDER BY distance
         LIMIT 5;",
    )?;

    let results = stmt.query_map(params![q_blob], |row| {
        Ok((
            row.get::<_, String>(0)?, // command
            row.get::<_, String>(1)?, // description
            row.get::<_, String>(2)?, // example_desc
            row.get::<_, String>(3)?, // example_cmd
            row.get::<_, f64>(4)?,    // distance (score)
        ))
    })?;

    let mut found_good_match = false;
    let mut current_cmd = String::new();
    // let mut current_desc = String::new();

    for result in results {
        let (cmd, desc, ex_desc, ex_cmd, score) = result?;
        println!("score: {}", score);
        if score > 0.9 {  // score closer to 1.0 is better
            if cmd != current_cmd {
                if !current_cmd.is_empty() {
                    println!();  // spacing between commands
                }
                println!("{}", cmd.bold().green());
                println!("{}", desc);
                current_cmd = cmd;
                // current_desc = desc;
            }

            print!("\n{} ", "Example".green());
            print!("{}", ex_desc);
            println!("\n  {}", ex_cmd.cyan());
            found_good_match = true;
        }
    }

    if !found_good_match {
        println!("No good matches found.");
    }

    Ok(())
}
