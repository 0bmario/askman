use clap::Parser;

/// askman – offline CLI helper
#[derive(Parser, Debug)]
#[command(
    version,
    about = "Ask natural language questions about Unix/Linux commands."
)]
pub struct Args {
    #[arg(required_unless_present = "clean")]
    pub question: Vec<String>,

    /// Remove the global settings, database, and model cache to uninstall
    #[arg(long, short = 'c')]
    pub clean: bool,

    /// Print internal matching scores (adjusted ranking distance, raw cosine distance, and applied heuristics)
    #[arg(long, short = 'v')]
    pub verbose: bool,

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
