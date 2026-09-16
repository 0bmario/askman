use anyhow::Result;
use askman::bundle::{BundleBuildOptions, build_matching_bundle, validate_matching_bundle};
use askman::dense::{
    DenseBuildOptions, DenseRecipe, DenseServerOptions, build_dense_index, run_query_server,
};
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
    /// Build and validate one self-contained offline matching bundle.
    BundleBuild {
        /// JSON manifest declaring the source metadata and selected files.
        #[arg(long)]
        manifest: PathBuf,
        /// Root of the provisioned local tldr snapshot.
        #[arg(long)]
        snapshot: PathBuf,
        /// Offline fastembed cache containing the pinned model snapshot.
        #[arg(long)]
        model_cache: PathBuf,
        /// Bundle directory to create or replace transactionally.
        #[arg(long)]
        output: PathBuf,
        /// CLI version/range compatible with this bundle.
        #[arg(long, default_value = env!("CARGO_PKG_VERSION"))]
        cli_compatibility: String,
    },
    /// Validate a previously built matching bundle without network access.
    BundleValidate {
        /// Bundle directory produced by `bundle-build`.
        #[arg(long)]
        bundle: PathBuf,
    },
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
    /// Add a pinned MiniLM vector index to a validated lexical artifact.
    DenseBuild {
        /// Validated lexical SQLite artifact produced by `build`.
        #[arg(long)]
        artifact: PathBuf,
        /// Offline fastembed cache containing the pinned model snapshot.
        #[arg(long)]
        model_cache: PathBuf,
        /// Replacement dense artifact. The lexical input is left untouched.
        #[arg(long)]
        output: PathBuf,
        /// Development-only embedding text representation.
        #[arg(long, default_value = "description")]
        recipe: String,
        /// Number of source examples passed to MiniLM per inference batch.
        #[arg(long, default_value_t = askman::dense::DEFAULT_BATCH_SIZE)]
        batch_size: usize,
    },
    /// Serve offline dense vector queries as JSON lines for the evaluator.
    DenseServer {
        /// Dense SQLite artifact produced by `dense-build`.
        #[arg(long)]
        artifact: PathBuf,
        /// Offline fastembed cache containing the pinned model snapshot.
        #[arg(long)]
        model_cache: PathBuf,
    },
}

fn main() -> Result<()> {
    match Args::parse().command {
        Command::BundleBuild {
            manifest,
            snapshot,
            model_cache,
            output,
            cli_compatibility,
        } => {
            let report = build_matching_bundle(BundleBuildOptions {
                manifest,
                snapshot,
                model_cache,
                output,
                cli_compatibility,
            })?;
            println!(
                "built matching bundle {} with {} pages and {} examples into {}",
                report.bundle_id,
                report.page_count,
                report.example_count,
                report.output.display()
            );
        }
        Command::BundleValidate { bundle } => {
            let manifest = validate_matching_bundle(&bundle)?;
            println!("valid matching bundle {}", manifest.bundle_id);
        }
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
            println!("excluded_files={}", report.excluded_count);
            println!("build_time_ms={}", report.build_time_ms);
            println!(
                "peak_memory_bytes={}",
                report
                    .peak_memory_bytes
                    .map_or_else(|| "unavailable".to_string(), |bytes| bytes.to_string())
            );
            println!("artifact_size_bytes={}", report.artifact_size_bytes);
            println!("hardware={}", report.hardware);
            println!("source_digest={}", report.source_digest);
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
        Command::DenseBuild {
            artifact,
            model_cache,
            output,
            recipe,
            batch_size,
        } => {
            let report = build_dense_index(DenseBuildOptions {
                artifact,
                model_cache,
                output,
                recipe: DenseRecipe::parse(&recipe)?,
                batch_size,
            })?;
            println!(
                "built dense {} index with {} examples into {}",
                report.recipe,
                report.indexed_examples,
                report.output.display()
            );
            println!("model_revision={}", report.model_revision);
            println!("build_time_ms={}", report.build_time_ms);
            println!(
                "peak_memory_bytes={}",
                report
                    .peak_memory_bytes
                    .map_or_else(|| "unavailable".to_string(), |bytes| bytes.to_string())
            );
            println!("artifact_size_bytes={}", report.artifact_size_bytes);
            println!("hardware={}", report.hardware);
        }
        Command::DenseServer {
            artifact,
            model_cache,
        } => run_query_server(DenseServerOptions {
            artifact,
            model_cache,
        })?,
    }

    Ok(())
}
