use anyhow::Result;

use askman::{
    bundle::BundleStore,
    cli::{self, LifecycleCommand},
    db,
    retrieval::run_active_candidate,
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
    run_active_candidate(
        &store,
        query,
        search::get_target_os(args.linux, args.osx, args.windows),
        args.linux || args.osx || args.windows,
        args.verbose,
    )
}
