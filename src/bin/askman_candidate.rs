#![cfg(feature = "dev")]

use anyhow::Result;
use askman::cli::CandidateArgs;
use askman::hybrid::{CandidateOptions, run_candidate};
use askman::search::get_target_os;
use clap::Parser;

fn main() -> Result<()> {
    let args = CandidateArgs::parse();
    let target_os = get_target_os(args.linux, args.osx, args.windows);

    run_candidate(CandidateOptions {
        bundle: args.bundle,
        query: args.question.join(" "),
        target_os,
        verbose: args.verbose,
    })
}
