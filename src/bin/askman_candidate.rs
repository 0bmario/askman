#![cfg(feature = "dev")]

use anyhow::Result;
use askman::cli::CandidateArgs;
use askman::hybrid::{CandidateOptions, query_candidate_results, run_expanded_dev_candidate};
use askman::search::get_target_os;
use clap::Parser;

fn main() -> Result<()> {
    let args = CandidateArgs::parse();
    let target_os = get_target_os(args.linux, args.osx, args.windows);

    let options = CandidateOptions {
        bundle: args.bundle,
        query: args.question.join(" "),
        target_os,
        platform_explicit: args.linux || args.osx || args.windows,
        verbose: args.verbose,
    };
    if args.json {
        println!(
            "{}",
            serde_json::to_string(&query_candidate_results(options)?)?
        );
        Ok(())
    } else {
        run_expanded_dev_candidate(options)
    }
}
