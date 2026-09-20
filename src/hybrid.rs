use crate::bundle::{load_validated_manifest, BundleManifest};
use crate::dense::{DenseCandidate, DenseIndex, DenseQueryMode};
use crate::search::TargetOs;
use crate::tldr_subset::{QueryOptions, QueryResult, query_artifact_for_platform};
use anyhow::{Result, bail};
use colored::Colorize;
use std::collections::{HashMap, HashSet};
use std::fmt::Write;
use std::fs;
use std::path::{Path, PathBuf};

pub const MAX_DISPLAYED_RESULTS: usize = 3;
pub const KEYWORD_CANDIDATE_BUDGET: usize = 8;
pub const DENSE_CANDIDATE_BUDGET: usize = 8;
pub const RRF_K: f64 = 60.0;
pub const KEYWORD_WEIGHT: f64 = 1.0;
// A small dense-side bias lets a guarded semantic hit clear the strict weak
// cutoff while keeping keyword-only hits fail-closed.
pub const DENSE_WEIGHT: f64 = 1.05;
// Expanded-dev tuning keeps strong semantic matches while rejecting the nearest
// unanswerable matches before rank fusion.
pub const DENSE_DISTANCE_CUTOFF: f64 = 0.55;
pub const WEAK_MATCH_CUTOFF: f64 = 0.50;
const FROZEN_DENSE_RECIPE: &str = "description";

#[derive(Debug, Clone, PartialEq)]
pub struct Candidate {
    pub example_id: String,
    pub page_id: String,
    pub page_command: String,
    pub example_command: String,
    pub page_description: String,
    pub example_description: String,
    pub source_path: String,
    pub source_ref: String,
    pub source_revision: String,
    pub platform: String,
    pub page_position: usize,
    pub example_position: usize,
    pub dense_distance: Option<f64>,
    pub ranking_score: f64,
}

#[derive(Debug, Clone)]
pub struct CandidateOptions {
    pub bundle: PathBuf,
    pub query: String,
    pub target_os: TargetOs,
    pub verbose: bool,
}

/// Run the shipping hybrid retrieval path with guarded dense-query expansion.
///
/// The expansion was tuned on the frozen `evaluation-v2` development split and
/// is bounded by the dense-distance guard before rank fusion plus the
/// fail-closed weak-match cutoff; raw queries remain available through the
/// dense-only diagnostics helper.
pub fn run_candidate(options: CandidateOptions) -> Result<()> {
    run_candidate_with_query_mode(options, DenseQueryMode::ExpandedDev)
}

/// Development alias: the dev-only candidate CLI runs the same guarded path.
#[cfg(feature = "dev")]
pub fn run_expanded_dev_candidate(options: CandidateOptions) -> Result<()> {
    run_candidate(options)
}

fn run_candidate_with_query_mode(
    options: CandidateOptions,
    query_mode: DenseQueryMode,
) -> Result<()> {
    let index = HybridIndex::open(&options.bundle)?;
    let result = (|| -> Result<()> {
        let fused = index.query(&options.query, options.target_os, query_mode)?;
        let displayed = display_candidates(&fused);
        print!("{}", render_results(&displayed, options.verbose));
        Ok(())
    })();
    // fastembed's native runtime can abort during teardown on hosts that
    // already loaded another ONNX Runtime. The candidate is a short-lived
    // process, so keep the runtime alive until process exit.
    std::mem::forget(index);
    result
}

struct HybridIndex {
    artifact: PathBuf,
    dense: DenseIndex,
}

impl HybridIndex {
    fn open(bundle: &Path) -> Result<Self> {
        let root = fs::canonicalize(bundle).map_err(|error| {
            anyhow::anyhow!(
                "failed to resolve matching bundle {}: {error}",
                bundle.display()
            )
        })?;
        let manifest = load_validated_manifest(&root)?;
        validate_frozen_bundle(&manifest)?;

        let artifact = root.join(&manifest.corpus.path);
        let model_cache = root.join("model-cache");
        let dense = DenseIndex::open_from_bundle(&artifact, &model_cache)?;
        Ok(Self { artifact, dense })
    }

    fn query(
        &self,
        query: &str,
        target_os: TargetOs,
        query_mode: DenseQueryMode,
    ) -> Result<Vec<Candidate>> {
        let keyword = query_artifact_for_platform(
            QueryOptions {
                artifact: self.artifact.clone(),
                query: query.to_string(),
                limit: KEYWORD_CANDIDATE_BUDGET,
            },
            target_os.as_str(),
        )?
        .into_iter()
        .map(candidate_from_keyword)
        .collect::<Vec<_>>();
        // The shipping entrypoint supplies Raw; only the dev entrypoint can
        // supply the experimental expansion mode.
        let dense = self
            .dense
            .query_with_mode(
                query,
                target_os.as_str(),
                DENSE_CANDIDATE_BUDGET,
                query_mode,
            )?
            .into_iter()
            .map(candidate_from_dense)
            .collect::<Vec<_>>();
        let dense = filter_dense_candidates(dense);

        fuse_candidates(&keyword, &dense)
    }
}

fn validate_frozen_bundle(manifest: &BundleManifest) -> Result<()> {
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

fn candidate_from_keyword(result: QueryResult) -> Candidate {
    Candidate {
        example_id: result.example_id,
        page_id: result.page_id,
        page_command: result.page_command,
        example_command: result.command,
        page_description: result.page_description,
        example_description: result.example_description,
        source_path: result.source_path,
        source_ref: result.source_ref,
        source_revision: result.source_revision,
        platform: result.platform,
        page_position: result.page_position,
        example_position: result.example_position,
        dense_distance: None,
        ranking_score: result.rank as f64,
    }
}

fn candidate_from_dense(result: DenseCandidate) -> Candidate {
    Candidate {
        example_id: result.example_id,
        page_id: result.page_id,
        page_command: result.page_command,
        example_command: result.command,
        page_description: result.page_description,
        example_description: result.example_description,
        source_path: result.source_path,
        source_ref: result.source_ref,
        source_revision: result.source_revision,
        platform: result.platform,
        page_position: result.page_position,
        example_position: result.example_position,
        dense_distance: Some(result.ranking_score),
        ranking_score: result.ranking_score,
    }
}

/// Fuse the bounded keyword and dense candidate rankings.
pub fn fuse_candidates(
    keyword_candidates: &[Candidate],
    dense_candidates: &[Candidate],
) -> Result<Vec<Candidate>> {
    let mut candidates_by_id = HashMap::<String, Candidate>::new();
    let mut scores_by_id = HashMap::<String, f64>::new();

    for (candidates, weight, budget) in [
        (keyword_candidates, KEYWORD_WEIGHT, KEYWORD_CANDIDATE_BUDGET),
        (dense_candidates, DENSE_WEIGHT, DENSE_CANDIDATE_BUDGET),
    ] {
        let mut seen_pages = HashSet::new();
        for (rank, candidate) in candidates
            .iter()
            .filter(|candidate| seen_pages.insert(candidate.page_id.as_str()))
            .take(budget)
            .enumerate()
        {
            let has_conflicting_identity =
                candidates_by_id
                    .get(&candidate.example_id)
                    .is_some_and(|previous| {
                        candidate_identity(previous) != candidate_identity(candidate)
                    });
            if has_conflicting_identity {
                bail!(
                    "candidate identity mismatch for {} between keyword and dense retrieval",
                    candidate.example_id
                );
            }

            candidates_by_id
                .entry(candidate.example_id.clone())
                .or_insert_with(|| candidate.clone());
            *scores_by_id
                .entry(candidate.example_id.clone())
                .or_insert(0.0) += weight / (RRF_K + rank as f64 + 1.0);
        }
    }

    let maximum_score = (KEYWORD_WEIGHT + DENSE_WEIGHT) / (RRF_K + 1.0);
    let mut ranked_ids = scores_by_id.keys().cloned().collect::<Vec<_>>();
    ranked_ids.sort_by(|left, right| {
        scores_by_id[right]
            .partial_cmp(&scores_by_id[left])
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.cmp(right))
    });

    Ok(ranked_ids
        .into_iter()
        .map(|example_id| {
            let mut candidate = candidates_by_id
                .remove(&example_id)
                .expect("every fused score has a candidate");
            candidate.ranking_score = scores_by_id[&example_id] / maximum_score;
            candidate
        })
        .collect())
}

/// Keep only candidates above the fail-closed weak-match cutoff and cap output
/// at three distinct destination pages.
pub fn display_candidates(fused_candidates: &[Candidate]) -> Vec<Candidate> {
    let mut seen_pages = HashSet::new();
    fused_candidates
        .iter()
        .filter(|candidate| candidate.ranking_score > WEAK_MATCH_CUTOFF)
        .filter(|candidate| seen_pages.insert(candidate.page_id.as_str()))
        .take(MAX_DISPLAYED_RESULTS)
        .cloned()
        .collect()
}

fn filter_dense_candidates(candidates: Vec<Candidate>) -> Vec<Candidate> {
    candidates
        .into_iter()
        .filter(|candidate| {
            candidate
                .dense_distance
                .is_some_and(|distance| distance <= DENSE_DISTANCE_CUTOFF)
        })
        .collect()
}

/// Render hybrid results using the existing Askman command/example layout.
pub fn render_results(results: &[Candidate], verbose: bool) -> String {
    let mut output = String::new();

    for candidate in results {
        writeln!(output, "{}", candidate.page_command.bold().green()).unwrap();
        if verbose {
            writeln!(
                output,
                "{}",
                format!(
                    "(Ranking score: {:.4} | Hybrid RRF rank)",
                    candidate.ranking_score
                )
                .bright_black()
            )
            .unwrap();
        }

        let clean_description = candidate
            .page_description
            .split_once(" More information:")
            .map_or(candidate.page_description.as_str(), |(description, _)| {
                description
            });
        writeln!(output, "{clean_description}").unwrap();

        output.push('\n');
        writeln!(output, "{}", "Examples:".underline()).unwrap();
        writeln!(output, "  {}", candidate.example_description).unwrap();
        writeln!(
            output,
            "   {}",
            crate::format::highlight_command(&candidate.example_command)
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

fn candidate_identity(
    candidate: &Candidate,
) -> (
    &str,
    &str,
    &str,
    &str,
    &str,
    &str,
    &str,
    &str,
    &str,
    usize,
    usize,
) {
    (
        &candidate.page_id,
        &candidate.page_command,
        &candidate.example_command,
        &candidate.page_description,
        &candidate.example_description,
        &candidate.source_path,
        &candidate.source_ref,
        &candidate.source_revision,
        &candidate.platform,
        candidate.page_position,
        candidate.example_position,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(example_id: &str, page_id: &str) -> Candidate {
        Candidate {
            example_id: example_id.to_string(),
            page_id: page_id.to_string(),
            page_command: "tool".to_string(),
            example_command: "tool --example".to_string(),
            page_description: "description".to_string(),
            example_description: "example".to_string(),
            source_path: format!("pages/common/{page_id}.md"),
            source_ref: format!("source:{page_id}"),
            source_revision: "revision".to_string(),
            platform: "common".to_string(),
            page_position: 1,
            example_position: 1,
            dense_distance: None,
            ranking_score: 0.0,
        }
    }

    #[test]
    fn weighted_rrf_rewards_agreement_between_retrievers() {
        let fused = fuse_candidates(
            &[
                candidate("shared", "page-shared"),
                candidate("keyword", "page-keyword"),
            ],
            &[
                candidate("dense", "page-dense"),
                candidate("shared", "page-shared"),
            ],
        )
        .unwrap();

        assert_eq!(
            fused
                .iter()
                .map(|candidate| candidate.example_id.as_str())
                .collect::<Vec<_>>(),
            vec!["shared", "dense", "keyword"]
        );
        let expected = (KEYWORD_WEIGHT / (RRF_K + 1.0) + DENSE_WEIGHT / (RRF_K + 2.0))
            / ((KEYWORD_WEIGHT + DENSE_WEIGHT) / (RRF_K + 1.0));
        assert!((fused[0].ranking_score - expected).abs() < 0.000_001);
    }

    #[test]
    fn weak_matches_abstain_and_display_is_limited_to_three_pages() {
        let fused = fuse_candidates(
            &[
                candidate("shared-a", "page-a"),
                candidate("shared-b", "page-b"),
                candidate("shared-c", "page-c"),
                candidate("shared-d", "page-d"),
                candidate("keyword-only", "page-keyword"),
            ],
            &[
                candidate("shared-a", "page-a"),
                candidate("shared-b", "page-b"),
                candidate("shared-c", "page-c"),
                candidate("shared-d", "page-d"),
                candidate("dense-only", "page-dense"),
            ],
        )
        .unwrap();

        let displayed = display_candidates(&fused);

        assert_eq!(
            displayed
                .iter()
                .map(|candidate| candidate.example_id.as_str())
                .collect::<Vec<_>>(),
            vec!["shared-a", "shared-b", "shared-c"]
        );

        let keyword_only = fuse_candidates(&[candidate("only", "page-only")], &[]).unwrap();
        assert!(keyword_only[0].ranking_score < WEAK_MATCH_CUTOFF);
        assert!(display_candidates(&keyword_only).is_empty());

        let mut dense_candidate = candidate("dense-only", "page-dense-only");
        dense_candidate.dense_distance = Some(DENSE_DISTANCE_CUTOFF);
        let dense_only = fuse_candidates(&[], &[dense_candidate]).unwrap();
        assert!(dense_only[0].ranking_score > WEAK_MATCH_CUTOFF);
        assert_eq!(display_candidates(&dense_only).len(), 1);
    }

    #[test]
    fn dense_distance_filter_rejects_weak_only_candidates() {
        let mut strong = candidate("strong", "page-strong");
        strong.dense_distance = Some(0.55);
        let mut weak = candidate("weak", "page-weak");
        weak.dense_distance = Some(0.56);

        let filtered = filter_dense_candidates(vec![strong, weak]);

        assert_eq!(
            filtered
                .iter()
                .map(|candidate| candidate.example_id.as_str())
                .collect::<Vec<_>>(),
            vec!["strong"]
        );
    }

    #[test]
    fn fusion_rejects_conflicting_source_identity_for_one_example_id() {
        let mut dense = candidate("shared", "page-other");
        dense.source_path = "pages/linux/page-other.md".to_string();

        let error = fuse_candidates(&[candidate("shared", "page-common")], &[dense])
            .unwrap_err()
            .to_string();

        assert!(error.contains("candidate identity mismatch"));
    }

    #[test]
    fn rendering_keeps_examples_traceable_without_confidence_language() {
        let mut result = candidate("example", "page");
        result.page_description = "Copy files. More information: https://example.test".to_string();
        result.example_description = "Copy one file:".to_string();
        result.example_command = "cp {{source}} {{destination}}".to_string();

        let output = render_results(&[result], false);

        assert!(output.contains("tool"));
        assert!(output.contains("Copy files."));
        assert!(output.contains("Copy one file:"));
        assert!(output.contains("cp"));
        assert!(!output.contains("More information:"));
        assert!(!output.contains('%'));
        assert!(!output.to_ascii_lowercase().contains("confidence"));
    }

    #[test]
    fn candidate_fails_closed_when_bundle_is_missing() {
        let root = tempfile::tempdir().unwrap();
        let error = run_candidate(CandidateOptions {
            bundle: root.path().join("missing-bundle"),
            query: "search files".to_string(),
            target_os: TargetOs::Linux,
            verbose: false,
        })
        .unwrap_err()
        .to_string();

        assert!(error.contains("failed to resolve matching bundle"));
    }

    #[test]
    fn policy_keeps_frozen_rrf_parameters_and_expanded_dev_guard() {
        let config: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/fixtures/evaluation/hybrid-config-v1.json"
        ))
        .unwrap();
        let selected = config["candidates"]
            .as_array()
            .unwrap()
            .iter()
            .find(|candidate| candidate["id"] == "rrf-k60-b8-cutoff-0.50")
            .unwrap();

        assert_eq!(selected["fusion"]["rrf_k"], 60);
        assert_eq!(selected["fusion"]["keyword_weight"], KEYWORD_WEIGHT);
        assert_eq!(selected["fusion"]["dense_weight"], 1.0);
        assert_eq!(
            selected["candidate_budgets"]["keyword"],
            KEYWORD_CANDIDATE_BUDGET
        );
        assert_eq!(
            selected["candidate_budgets"]["dense"],
            DENSE_CANDIDATE_BUDGET
        );
        assert_eq!(DENSE_DISTANCE_CUTOFF, 0.55);
        assert_eq!(WEAK_MATCH_CUTOFF, 0.50);
    }

    #[test]
    fn policy_matches_the_expanded_development_configuration() {
        let config: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/fixtures/evaluation/hybrid-config-expanded-dev-v1.json"
        ))
        .unwrap();
        let policy = &config["policy"];

        assert_eq!(policy["fusion"]["rrf_k"], RRF_K as u64);
        assert_eq!(policy["fusion"]["keyword_weight"], KEYWORD_WEIGHT);
        assert_eq!(policy["fusion"]["dense_weight"], DENSE_WEIGHT);
        assert_eq!(
            policy["candidate_budgets"]["keyword"],
            KEYWORD_CANDIDATE_BUDGET
        );
        assert_eq!(policy["candidate_budgets"]["dense"], DENSE_CANDIDATE_BUDGET);
        assert_eq!(policy["dense_distance_cutoff"], DENSE_DISTANCE_CUTOFF);
        assert_eq!(policy["weak_match_cutoff"], WEAK_MATCH_CUTOFF);
    }
}
