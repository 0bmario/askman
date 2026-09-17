use clap::Parser;
use std::path::PathBuf;

/// askman – offline CLI helper
#[derive(Parser, Debug)]
#[command(
    version,
    about = "Ask natural language questions about Unix/Linux commands."
)]
pub struct Args {
    /// A natural-language query, or one of the explicit lifecycle commands:
    /// `setup`, `update`, or `rollback`.
    #[arg(required_unless_present = "clean")]
    pub question: Vec<String>,

    /// Remove the global settings, database, and model cache to uninstall
    #[arg(long, short = 'c')]
    pub clean: bool,

    /// Print internal matching scores: adjusted ranking distance, raw L2
    /// distance, and applied heuristics.
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LifecycleCommand {
    Setup,
    Update,
    Rollback,
}

pub fn lifecycle_command(question: &[String]) -> Option<LifecycleCommand> {
    match question {
        [command] if command == "setup" => Some(LifecycleCommand::Setup),
        [command] if command == "update" => Some(LifecycleCommand::Update),
        [command] if command == "rollback" => Some(LifecycleCommand::Rollback),
        _ => None,
    }
}

/// Development-only candidate CLI backed by one validated matching bundle.
#[derive(Parser, Debug)]
#[command(
    name = "askman_candidate",
    version,
    about = "Ask natural language questions using frozen hybrid retrieval."
)]
pub struct CandidateArgs {
    #[arg(required = true)]
    pub question: Vec<String>,

    /// Validated matching bundle containing lexical, dense, and model assets
    #[arg(long, required = true, value_name = "DIR")]
    pub bundle: PathBuf,

    /// Print the hybrid ranking score for diagnostics.
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn candidate_cli_requires_an_explicit_bundle_and_parses_platform_flags() {
        let args = CandidateArgs::try_parse_from([
            "askman_candidate",
            "--bundle",
            "/tmp/matching-bundle",
            "--linux",
            "search",
            "files",
        ])
        .unwrap();

        assert_eq!(args.bundle, PathBuf::from("/tmp/matching-bundle"));
        assert_eq!(args.question, ["search", "files"]);
        assert!(args.linux);
        assert!(!args.osx);
        assert!(!args.windows);
        assert!(CandidateArgs::try_parse_from(["askman_candidate", "search"]).is_err());
        assert!(CandidateArgs::try_parse_from(["askman_candidate", "search", "files"]).is_err());
    }

    #[test]
    fn lifecycle_commands_are_explicit_single_words() {
        assert_eq!(
            lifecycle_command(&["setup".to_string()]),
            Some(LifecycleCommand::Setup)
        );
        assert_eq!(
            lifecycle_command(&["update".to_string()]),
            Some(LifecycleCommand::Update)
        );
        assert_eq!(
            lifecycle_command(&["rollback".to_string()]),
            Some(LifecycleCommand::Rollback)
        );
        assert_eq!(
            lifecycle_command(&["update", "files"].map(str::to_string)),
            None
        );
    }
}
