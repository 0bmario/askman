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

    /// Force search for Linux commands
    #[arg(long)]
    pub linux: bool,

    /// Force search for macOS commands
    #[arg(long)]
    pub osx: bool,

    /// Force search for Windows commands
    #[arg(long)]
    pub windows: bool,
}
