use crate::bundle::{BundleManifest, BundleStore, ValidatedBundle};
use crate::dense::{
    DenseCandidate, DenseIndex, DenseQueryMode, is_file_stdout_query_excluding_cat,
    is_negated_exif_observation_query, is_negated_file_stdout_query,
};
use crate::search::TargetOs;
use anyhow::{Result, bail};
use colored::Colorize;
use std::fmt::Write;
use std::path::PathBuf;

pub const MAX_DISPLAYED_RESULTS: usize = 3;
pub const DENSE_CANDIDATE_BUDGET: usize = 8;
pub const DENSE_DISTANCE_CUTOFF: f64 = 0.55;
const FROZEN_DENSE_RECIPE: &str = "main-compatible";

#[derive(Debug, Clone)]
pub struct CandidateOptions {
    pub bundle: PathBuf,
    pub query: String,
    pub target_os: TargetOs,
    pub platform_explicit: bool,
    pub verbose: bool,
}

pub fn run_candidate(options: CandidateOptions) -> Result<()> {
    let bundle = ValidatedBundle::open(&options.bundle)?;
    run_validated_candidate(
        bundle,
        options.query,
        options.target_os,
        options.platform_explicit,
        options.verbose,
    )
}

pub fn run_active_candidate(
    store: &BundleStore,
    query: String,
    target_os: TargetOs,
    platform_explicit: bool,
    verbose: bool,
) -> Result<()> {
    run_validated_candidate(
        store.active_validated_bundle()?,
        query,
        target_os,
        platform_explicit,
        verbose,
    )
}

fn run_validated_candidate(
    bundle: ValidatedBundle,
    query: String,
    target_os: TargetOs,
    platform_explicit: bool,
    verbose: bool,
) -> Result<()> {
    validate_bundle(bundle.manifest())?;
    let index = DenseIndex::open_from_bundle(&bundle)?;
    let result = (|| -> Result<()> {
        let results = select_displayed_candidates(
            &query,
            index.query_with_mode(
                &query,
                target_os.as_str(),
                DENSE_CANDIDATE_BUDGET,
                DenseQueryMode::FocusedIntentRulesV1,
                platform_explicit,
                false,
            )?,
        );
        print!("{}", render_results(&results, verbose));
        Ok(())
    })();
    // The native ONNX runtime can abort during teardown on supported hosts.
    std::mem::forget(index);
    result
}

fn select_displayed_candidates(
    query: &str,
    candidates: impl IntoIterator<Item = DenseCandidate>,
) -> Vec<DenseCandidate> {
    if is_negated_exif_observation_query(query)
        || is_negated_file_stdout_query(query)
        || is_file_stdout_query_excluding_cat(query)
    {
        return Vec::new();
    }

    candidates
        .into_iter()
        .filter(|candidate| candidate.ranking_score <= DENSE_DISTANCE_CUTOFF)
        .take(MAX_DISPLAYED_RESULTS)
        .collect()
}

fn validate_bundle(manifest: &BundleManifest) -> Result<()> {
    let expected_cli = format!("askman={}", env!("CARGO_PKG_VERSION"));
    if manifest.cli_compatibility != expected_cli {
        bail!(
            "matching bundle CLI compatibility is {}, expected {}",
            manifest.cli_compatibility,
            expected_cli
        );
    }
    if manifest.dense_index.recipe != FROZEN_DENSE_RECIPE {
        bail!(
            "matching bundle dense recipe is {}, expected {}",
            manifest.dense_index.recipe,
            FROZEN_DENSE_RECIPE
        );
    }
    Ok(())
}

fn render_results(results: &[DenseCandidate], verbose: bool) -> String {
    let mut output = String::new();
    for candidate in results {
        writeln!(output, "{}", candidate.page_command.bold().green()).unwrap();
        if verbose {
            writeln!(
                output,
                "{}",
                format!(
                    "(Distance: {:.4} | Raw cosine distance)",
                    candidate.ranking_score
                )
                .bright_black()
            )
            .unwrap();
        }

        let description = candidate
            .page_description
            .split_once("More information:")
            .map_or(candidate.page_description.as_str(), |(description, _)| {
                description.trim_end()
            });
        writeln!(output, "{description}").unwrap();
        output.push('\n');
        writeln!(output, "{}", "Examples:".underline()).unwrap();
        writeln!(output, "  {}", candidate.example_description).unwrap();
        writeln!(
            output,
            "   {}",
            crate::format::highlight_command(&candidate.command)
        )
        .unwrap();
        output.push('\n');
        output.push('\n');
    }

    if results.is_empty() {
        output.push_str("No good matches found.\n");
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(distance: f64) -> DenseCandidate {
        DenseCandidate {
            example_id: "example".to_string(),
            page_id: "page".to_string(),
            page_command: "sample".to_string(),
            command: "sample value".to_string(),
            page_description: "Sample page.".to_string(),
            example_description: "Run sample.".to_string(),
            source_path: "common/sample.md".to_string(),
            source_ref: "sample".to_string(),
            source_revision: "revision".to_string(),
            platform: "common".to_string(),
            page_position: 0,
            example_position: 0,
            ranking_score: distance,
        }
    }

    #[test]
    fn guarded_results_keep_the_cutoff_boundary_and_cap_three() {
        let results = select_displayed_candidates(
            "copy one file to another path",
            [
                candidate(0.55),
                candidate(0.56),
                candidate(0.1),
                candidate(0.2),
                candidate(0.3),
            ],
        );

        assert_eq!(results.len(), 3);
        assert_eq!(results[0].ranking_score, DENSE_DISTANCE_CUTOFF);
        assert_eq!(results[1].ranking_score, 0.1);
        assert_eq!(results[2].ranking_score, 0.2);
        assert!(results.iter().all(|result| result.ranking_score <= 0.55));
    }

    #[test]
    fn negated_exif_observation_abstains_from_positive_examples() {
        let displayed =
            select_displayed_candidates("do not read EXIF metadata from a photo", [candidate(0.1)]);

        assert!(displayed.is_empty());
    }

    #[test]
    fn negated_file_stdout_request_abstains_from_positive_examples() {
        let displayed =
            select_displayed_candidates("do not show file contents to stdout", [candidate(0.1)]);

        assert!(displayed.is_empty());
    }

    #[test]
    fn file_stdout_request_abstains_when_its_only_documented_example_is_excluded() {
        let displayed = select_displayed_candidates(
            "print file contents to stdout without using cat",
            [candidate(0.1)],
        );

        assert!(displayed.is_empty());
    }

    #[test]
    fn abstention_has_a_stable_user_message() {
        assert_eq!(render_results(&[], false), "No good matches found.\n");
    }
}
