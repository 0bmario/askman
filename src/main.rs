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

    let q_vec = embedder.embed(vec![query], None)?[0].clone();
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

    // Group examples by command
    let mut command_map: std::collections::HashMap<String, (String, Vec<(String, String)>)> =
        std::collections::HashMap::new();
    
    for result in results {
        let (cmd, desc, ex_desc, ex_cmd, score) = result?;
        
        if score < 0.7 {
            continue;
        }
        
        if command_map.contains_key(&cmd) {
            // cmd exists, add the example
            let examples = &mut command_map.get_mut(&cmd).unwrap().1;
            examples.push((ex_desc, ex_cmd));
        } else {
            // new cmd, create entry with description and first example
            command_map.insert(cmd, (desc, vec![(ex_desc, ex_cmd)]));
        }
    }
    
    // display results
    for (cmd, (desc, examples)) in &command_map {
        println!("{}", cmd.bold().green());
        println!("{}", desc);
        
        if !examples.is_empty() {
            println!("\n{}", "Examples:".underline());
            
            for (i, (ex_desc, ex_cmd)) in examples.iter().enumerate() {
                println!("  {}", ex_desc);
                println!("   {}", ex_cmd.cyan());
                
                if i < examples.len() - 1 {
                    println!();
                }
            }
        }
        
        println!();
    }
    
    if command_map.is_empty() {
        println!("No good matches found.");
    }

    Ok(())
}

