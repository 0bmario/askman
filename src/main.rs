use anyhow::Result;

use askman::{
    bundle::BundleStore,
    cli::{self, LifecycleCommand},
    db,
    hybrid::{
        CandidateOptions, query_candidate_results_with_validated_bundle,
        query_legacy_json_with_validated_bundle, run_candidate_with_validated_bundle,
    },
    search,
};
use clap::Parser;
use rusqlite::ffi::sqlite3_auto_extension;
use sqlite_vec::sqlite3_vec_init;

fn main() -> Result<()> {
    // Required: register sqlite-vec extension before opening any connection
    unsafe {
        sqlite3_auto_extension(Some(std::mem::transmute(sqlite3_vec_init as *const ())));
    }

    let args = cli::Args::parse();

    if args.clean {
        let app_dir = db::get_app_dir_path();
        println!("Cleaning up askman application data...");
        if app_dir.exists() {
            if let Err(e) = std::fs::remove_dir_all(&app_dir) {
                eprintln!(
                    "Failed to remove data directory: {}. Please delete it manually at {:?}",
                    e, app_dir
                );
            } else {
                println!(
                    "Successfully removed configuration, database, and models from {:?}",
                    app_dir
                );
            }
        } else {
            println!("No data directory found at {:?}", app_dir);
        }
        return Ok(());
    }

    let app_dir = db::get_app_dir_path();
    let store = BundleStore::new(&app_dir);

    if let Some(command) = cli::lifecycle_command(&args.question) {
        let manifest = match command {
            LifecycleCommand::Setup => store.setup()?,
            LifecycleCommand::Update => store.update()?,
            LifecycleCommand::Rollback => store.rollback()?,
        };
        println!("active matching bundle {}", manifest.bundle_id);
        return Ok(());
    }

    let query = args.question.join(" ");
    let (bundle, validated) = store.active_validated_bundle()?;
    let options = CandidateOptions {
        bundle,
        query,
        target_os: search::get_target_os(args.linux, args.osx, args.windows),
        platform_explicit: args.linux || args.osx || args.windows,
        verbose: args.verbose,
    };
    if args.ci_json_v1 {
        println!(
            "{}",
            serde_json::to_string(&query_candidate_results_with_validated_bundle(
                options, validated,
            )?)?
        );
        Ok(())
    } else if args.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&query_legacy_json_with_validated_bundle(
                options,
                args.verbose,
                validated,
            )?)?
        );
        Ok(())
    } else {
        run_candidate_with_validated_bundle(options, validated)
    }
}
