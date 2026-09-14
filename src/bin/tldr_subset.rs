use anyhow::Result;
use askman::tldr_subset::{
    BuildOptions, InspectOptions, QueryOptions, build_artifact, inspect_page,
    query_artifact_for_platform,
};
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
        /// Target operating system. Common is used when no target override exists.
        #[arg(long, alias = "os", default_value = "common")]
        platform: String,
    },
    /// Inspect the selected full page, following references and listing disambiguation destinations.
    Inspect {
        /// SQLite artifact produced by `build`.
        #[arg(long)]
        artifact: PathBuf,
        /// Page name or command, such as `git commit`.
        #[arg(long)]
        page: String,
        /// Target operating system. Common is used when no target override exists.
        #[arg(long, alias = "os", default_value = "common")]
        platform: String,
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
            platform,
        } => {
            let results = query_artifact_for_platform(
                QueryOptions {
                    artifact,
                    query,
                    limit,
                },
                &platform,
            )?;
            println!("{}", serde_json::to_string_pretty(&results)?);
        }
        Command::Inspect {
            artifact,
            page,
            platform,
        } => {
            let result = inspect_page(InspectOptions {
                artifact,
                page,
                platform,
            })?;
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
    }

    Ok(())
}
