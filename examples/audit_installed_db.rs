use anyhow::{Context, Result};
use rusqlite::{Connection, OpenFlags, ffi::sqlite3_auto_extension};
use sqlite_vec::sqlite3_vec_init;
use std::{env, mem::transmute};

fn main() -> Result<()> {
    unsafe {
        sqlite3_auto_extension(Some(transmute(sqlite3_vec_init as *const ())));
    }

    let database = env::args_os()
        .nth(1)
        .context("usage: audit_installed_db <commands.db>")?;
    let connection = Connection::open_with_flags(
        database,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;

    let (rows, commands, platforms, empty_commands, empty_descriptions, empty_examples): (
        i64,
        i64,
        i64,
        i64,
        i64,
        i64,
    ) = connection.query_row(
        "SELECT COUNT(*), COUNT(DISTINCT command), COUNT(DISTINCT os),
                SUM(CASE WHEN command IS NULL OR TRIM(command) = '' THEN 1 ELSE 0 END),
                SUM(CASE WHEN description IS NULL OR TRIM(description) = '' THEN 1 ELSE 0 END),
                SUM(CASE WHEN example_cmd IS NULL OR TRIM(example_cmd) = '' THEN 1 ELSE 0 END)
         FROM pages_vec",
        [],
        |row| {
            Ok((
                row.get(0)?,
                row.get(1)?,
                row.get(2)?,
                row.get(3)?,
                row.get(4)?,
                row.get(5)?,
            ))
        },
    )?;
    println!("rows={rows}");
    println!("distinct_commands={commands}");
    println!("platforms={platforms}");
    println!("empty_command_rows={empty_commands}");
    println!("empty_description_rows={empty_descriptions}");
    println!("empty_example_command_rows={empty_examples}");

    let mut statement = connection.prepare(
        "SELECT os, COUNT(*), COUNT(DISTINCT command)
         FROM pages_vec GROUP BY os ORDER BY os",
    )?;
    for row in statement.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, i64>(1)?,
            row.get::<_, i64>(2)?,
        ))
    })? {
        let (platform, rows, commands) = row?;
        println!("platform.{platform}.rows={rows}");
        println!("platform.{platform}.commands={commands}");
    }

    let pages_with_multiple_examples: i64 = connection.query_row(
        "SELECT COUNT(*) FROM (
            SELECT command, os FROM pages_vec GROUP BY command, os HAVING COUNT(*) > 1
         )",
        [],
        |row| row.get(0),
    )?;
    let duplicate_example_groups: i64 = connection.query_row(
        "SELECT COUNT(*) FROM (
            SELECT command, os, example_desc, example_cmd
            FROM pages_vec GROUP BY command, os, example_desc, example_cmd HAVING COUNT(*) > 1
         )",
        [],
        |row| row.get(0),
    )?;
    let navigation_rows: i64 = connection.query_row(
        "SELECT COUNT(*) FROM pages_vec WHERE lower(command) = 'tldr'",
        [],
        |row| row.get(0),
    )?;
    println!("pages_with_multiple_examples={pages_with_multiple_examples}");
    println!("duplicate_example_groups={duplicate_example_groups}");
    println!("tldr_navigation_rows={navigation_rows}");
    Ok(())
}
