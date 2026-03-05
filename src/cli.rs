use clap::{Parser, Subcommand};

#[derive(Subcommand, Debug)]
pub enum Command {
    /// Update askman binary and bundled commands database
    Update,
}

/// askman – offline CLI helper
#[derive(Parser, Debug)]
#[command(
    version,
    about = "Ask natural language questions about terminal commands.",
    subcommand_negates_reqs = true,
    args_conflicts_with_subcommands = true
)]
pub struct Args {
    #[arg(required_unless_present_any = ["clean", "update"])]
    pub question: Vec<String>,

    #[command(subcommand)]
    pub command: Option<Command>,

    /// Remove the global settings, database, and model cache to uninstall
    #[arg(long, short = 'c', conflicts_with_all = ["update", "question"])]
    pub clean: bool,

    /// Update askman binary and bundled commands database
    #[arg(long, short = 'u', conflicts_with = "question")]
    pub update: bool,

    /// Print internal matching scores (adjusted ranking distance, raw cosine distance, and applied heuristics)
    #[arg(long, short = 'v')]
    pub verbose: bool,

    /// Output results in JSON format, cross-platform
    #[arg(long, short = 'j')]
    pub json: bool,

    /// Force search for Linux commands
    #[arg(long, conflicts_with_all = ["osx", "windows"])]
    pub linux: bool,

    /// Force search for macOS commands
    #[arg(long, conflicts_with_all = ["linux", "windows"])]
    pub osx: bool,

    /// Force search for Windows commands
    #[arg(long, conflicts_with_all = ["linux", "osx"])]
    pub windows: bool,
}
