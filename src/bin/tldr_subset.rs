use anyhow::Result;
use askman::tldr_subset::{BuildOptions, QueryOptions, build_artifact, query_artifact};
use clap::{Parser, Subcommand};
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(name = "tldr_subset", about = "Build and query a pinned tldr subset")]
struct Args {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Build a replacement SQLite artifact from a provisioned local snapshot.
    Build {
        /// JSON manifest declaring the source metadata and selected files.
        #[arg(long)]
        manifest: PathBuf,
        /// Root of the provisioned local snapshot containing the manifest paths.
        #[arg(long)]
        snapshot: PathBuf,
        /// Output artifact. This is separate from Askman's installed database.
        #[arg(long)]
        output: PathBuf,
    },
    /// Run keyword retrieval against a previously built artifact.
    Query {
        /// SQLite artifact produced by `build`.
        #[arg(long)]
        artifact: PathBuf,
        /// Natural-language keyword query.
        #[arg(long)]
        query: String,
        /// Maximum number of examples to return.
        #[arg(long, default_value_t = 10)]
        limit: usize,
    },
}

fn main() -> Result<()> {
    match Args::parse().command {
        Command::Build {
            manifest,
            snapshot,
            output,
        } => {
            let report = build_artifact(BuildOptions {
                manifest,
                snapshot,
                output,
            })?;
            println!(
                "built {} pages, {} examples from {} files into {}",
                report.page_count,
                report.example_count,
                report.file_count,
                report.output.display()
            );
        }
        Command::Query {
            artifact,
            query,
            limit,
        } => {
            let results = query_artifact(QueryOptions {
                artifact,
                query,
                limit,
            })?;
            println!("{}", serde_json::to_string_pretty(&results)?);
        }
    }

    Ok(())
}
