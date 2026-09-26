//! Experimental rank-fusion implementation retained for controlled ablations.
//! The shipping CLI uses dense-only retrieval from `crate::retrieval`.

use crate::bundle::{BundleManifest, BundleStore, ValidatedBundle};
use crate::dense::{
    DenseCandidate, DenseIndex, DenseQueryMode, expanded_query_phrases_for_platform,
    is_negated_exif_observation_query,
};
use crate::search::TargetOs;
use crate::tldr_subset::{QueryResult, ValidatedLexicalIndex};
use anyhow::{Result, bail};
use colored::Colorize;
use std::collections::{HashMap, HashSet};
use std::fmt::Write;
use std::path::PathBuf;

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
const FROZEN_DENSE_RECIPE: &str = "main-compatible";

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
    /// True when the user passed an explicit --linux/--osx/--windows flag;
    /// enables target-platform-over-common ordering. Host-default queries
    /// keep pure relevance ordering.
    pub platform_explicit: bool,
    pub verbose: bool,
}

/// Run the hybrid retrieval ablation with guarded dense-query expansion.
///
/// The expansion was tuned on the frozen `evaluation-v2` development split and
/// is bounded by the dense-distance guard before rank fusion plus the
/// fail-closed weak-match cutoff; raw queries remain available through the
/// dense-only diagnostics helper.
pub fn run_candidate(options: CandidateOptions) -> Result<()> {
    run_candidate_with_query_mode(options, DenseQueryMode::IntentRulesV1)
}

pub fn run_active_candidate(
    store: &BundleStore,
    query: String,
    target_os: TargetOs,
    platform_explicit: bool,
    verbose: bool,
) -> Result<()> {
    run_candidate_with_validated_bundle(
        store.active_validated_bundle()?,
        query,
        target_os,
        platform_explicit,
        verbose,
    )
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
    let bundle = ValidatedBundle::open(&options.bundle)?;
    run_candidate_with_validated_bundle_and_query_mode(
        bundle,
        options.query,
        options.target_os,
        options.platform_explicit,
        options.verbose,
        query_mode,
    )
}

pub(crate) fn run_candidate_with_validated_bundle(
    bundle: ValidatedBundle,
    query: String,
    target_os: TargetOs,
    platform_explicit: bool,
    verbose: bool,
) -> Result<()> {
    run_candidate_with_validated_bundle_and_query_mode(
        bundle,
        query,
        target_os,
        platform_explicit,
        verbose,
        DenseQueryMode::IntentRulesV1,
    )
}

fn run_candidate_with_validated_bundle_and_query_mode(
    bundle: ValidatedBundle,
    query: String,
    target_os: TargetOs,
    platform_explicit: bool,
    verbose: bool,
    query_mode: DenseQueryMode,
) -> Result<()> {
    let index = HybridIndex::open_validated(bundle)?;
    let result = (|| -> Result<()> {
        let fused = index.query(&query, target_os, query_mode, platform_explicit)?;
        let displayed = display_query_candidates(&query, &fused);
        print!("{}", render_results(&displayed, verbose));
        Ok(())
    })();
    // fastembed's native runtime can abort during teardown on hosts that
    // already loaded another ONNX Runtime. The candidate is a short-lived
    // process, so keep the runtime alive until process exit.
    std::mem::forget(index);
    result
}

struct HybridIndex {
    lexical: ValidatedLexicalIndex,
    dense: DenseIndex,
}

impl HybridIndex {
    fn open_validated(bundle: ValidatedBundle) -> Result<Self> {
        validate_frozen_bundle(bundle.manifest())?;
        let dense = DenseIndex::open_from_bundle(&bundle)?;
        let lexical = ValidatedLexicalIndex::open(&bundle)?;
        Ok(Self { lexical, dense })
    }

    fn query(
        &self,
        query: &str,
        target_os: TargetOs,
        query_mode: DenseQueryMode,
        platform_explicit: bool,
    ) -> Result<Vec<Candidate>> {
        let selected_pages = self.lexical.selected_page_ids(target_os.as_str())?;
        let keyword = query_keyword_candidates(
            &self.lexical,
            query,
            target_os.as_str(),
            &selected_pages,
            query_mode,
            platform_explicit,
        )?;
        // The shipping entrypoint uses guarded expansion too; lower-level
        // dense diagnostics can still request raw query text.
        let dense = self
            .dense
            .query_with_selected_pages(
                query,
                target_os.as_str(),
                DENSE_CANDIDATE_BUDGET,
                &selected_pages,
                query_mode,
                platform_explicit,
            )?
            .into_iter()
            .map(candidate_from_dense)
            .collect::<Vec<_>>();
        let dense = filter_dense_candidates(dense);

        fuse_query_candidates(query, &keyword, &dense, platform_explicit)
    }
}

fn keyword_query_texts(query: &str, query_mode: DenseQueryMode, platform: &str) -> Vec<String> {
    expanded_query_phrases_for_platform(query, query_mode, platform)
        .into_iter()
        .map(str::to_string)
        .chain(std::iter::once(query.to_string()))
        .collect()
}

fn query_keyword_candidates(
    lexical: &ValidatedLexicalIndex,
    query: &str,
    platform: &str,
    selected_page_ids: &[String],
    query_mode: DenseQueryMode,
    platform_explicit: bool,
) -> Result<Vec<Candidate>> {
    let mut candidates = Vec::new();
    let mut seen_pages = HashSet::new();
    let query_texts = keyword_query_texts(query, query_mode, platform);
    let fallback_query = query_texts.last();

    for query_text in query_texts.iter().take(query_texts.len().saturating_sub(1)) {
        let results = lexical.query_for_platform(
            query_text,
            platform,
            selected_page_ids,
            KEYWORD_CANDIDATE_BUDGET,
            platform_explicit,
        )?;
        if append_keyword_results(&mut candidates, &mut seen_pages, results) {
            return Ok(candidates);
        }
    }

    // The focused phrases mirror indexed examples. If one returns results,
    // the original query is only a broader, redundant lexical pass; keep it
    // as a fallback when none of the focused phrases match.
    if candidates.is_empty()
        && let Some(query_text) = fallback_query
    {
        let results = lexical.query_for_platform(
            query_text,
            platform,
            selected_page_ids,
            KEYWORD_CANDIDATE_BUDGET,
            platform_explicit,
        )?;
        append_keyword_results(&mut candidates, &mut seen_pages, results);
    }

    Ok(candidates)
}

fn append_keyword_results(
    candidates: &mut Vec<Candidate>,
    seen_pages: &mut HashSet<String>,
    results: Vec<QueryResult>,
) -> bool {
    for result in results {
        let candidate = candidate_from_keyword(result);
        if seen_pages.insert(candidate.page_id.clone()) {
            candidates.push(candidate);
        }
        if candidates.len() == KEYWORD_CANDIDATE_BUDGET {
            return true;
        }
    }
    false
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
    fuse_candidates_for_query(keyword_candidates, dense_candidates, false)
}

fn fuse_candidates_for_query(
    keyword_candidates: &[Candidate],
    dense_candidates: &[Candidate],
    platform_explicit: bool,
) -> Result<Vec<Candidate>> {
    fuse_ranked_candidates(
        keyword_candidates,
        dense_candidates,
        platform_explicit,
        None,
    )
}

fn fuse_ranked_candidates(
    keyword_candidates: &[Candidate],
    dense_candidates: &[Candidate],
    platform_explicit: bool,
    query: Option<&str>,
) -> Result<Vec<Candidate>> {
    let mut candidates_by_id = HashMap::<String, Candidate>::new();
    let mut candidate_ids_by_page = HashMap::<String, Vec<String>>::new();
    let mut scores_by_example = HashMap::<String, f64>::new();
    let mut scores_by_page = HashMap::<String, f64>::new();
    let mut rank_weights_by_page = HashMap::<String, f64>::new();
    let requested_action = query.and_then(requested_network_action);
    let requires_tar_extraction = query.is_some_and(requests_tar_archive_extraction);
    let requires_dns_cache_invalidation = query.is_some_and(requests_dns_cache_invalidation);
    let requires_recursive_text_search = query.is_some_and(requests_recursive_text_search);

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
            rank_weights_by_page
                .entry(candidate.page_id.clone())
                .or_insert_with(|| {
                    let main_compatible_weight = crate::search::main_compatible_rank_weight(
                        &candidate.page_command,
                        &candidate.page_description,
                    );
                    if platform_explicit && candidate.platform == "common" {
                        // Keep the legacy core-command boost from displacing
                        // a strong match for an explicitly requested platform.
                        main_compatible_weight.min(1.0)
                    } else {
                        main_compatible_weight
                    }
                });
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

            let contribution = weight / (RRF_K + rank as f64 + 1.0);
            *scores_by_page
                .entry(candidate.page_id.clone())
                .or_insert(0.0) += contribution;

            let demonstrates_network_action = requested_action
                .is_none_or(|action| candidate_supports_network_action(candidate, action));
            let demonstrates_tar_extraction =
                !requires_tar_extraction || candidate_supports_archive_extraction(candidate);
            let demonstrates_dns_cache_invalidation = !requires_dns_cache_invalidation
                || candidate_supports_dns_cache_invalidation(candidate);
            let demonstrates_recursive_text_search = !requires_recursive_text_search
                || candidate_supports_recursive_text_search(candidate);
            if !demonstrates_network_action
                || !demonstrates_tar_extraction
                || !demonstrates_dns_cache_invalidation
                || !demonstrates_recursive_text_search
            {
                continue;
            }

            if !candidates_by_id.contains_key(&candidate.example_id) {
                candidate_ids_by_page
                    .entry(candidate.page_id.clone())
                    .or_default()
                    .push(candidate.example_id.clone());
                candidates_by_id.insert(candidate.example_id.clone(), candidate.clone());
            }
            *scores_by_example
                .entry(candidate.example_id.clone())
                .or_insert(0.0) += contribution;
        }
    }

    let maximum_score = (KEYWORD_WEIGHT + DENSE_WEIGHT) / (RRF_K + 1.0);
    let maximum_rank_weight = candidate_ids_by_page
        .keys()
        .filter_map(|page_id| rank_weights_by_page.get(page_id))
        .copied()
        .reduce(f64::max)
        .unwrap_or(1.0);
    let mut ranked_page_ids = candidate_ids_by_page.keys().cloned().collect::<Vec<_>>();
    ranked_page_ids.sort_by(|left, right| {
        let left_score = scores_by_page[left] * rank_weights_by_page[left];
        let right_score = scores_by_page[right] * rank_weights_by_page[right];
        right_score
            .partial_cmp(&left_score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.cmp(right))
    });

    Ok(ranked_page_ids
        .into_iter()
        .map(|page_id| {
            let best_example_id = candidate_ids_by_page
                .remove(&page_id)
                .expect("every fused score has a page candidate")
                .into_iter()
                .max_by(|left, right| {
                    scores_by_example[left]
                        .total_cmp(&scores_by_example[right])
                        .then_with(|| right.cmp(left))
                })
                .expect("every fused page has at least one example");
            let mut candidate = candidates_by_id
                .remove(&best_example_id)
                .expect("every fused example has a candidate");
            candidate.ranking_score = scores_by_page[&page_id] * rank_weights_by_page[&page_id]
                / (maximum_score * maximum_rank_weight);
            candidate
        })
        .collect())
}

fn fuse_query_candidates(
    query: &str,
    keyword_candidates: &[Candidate],
    dense_candidates: &[Candidate],
    platform_explicit: bool,
) -> Result<Vec<Candidate>> {
    let fused = fuse_ranked_candidates(
        &keyword_candidates,
        &dense_candidates,
        platform_explicit,
        Some(query),
    )?;
    Ok(filter_explicit_nftables_tool(query, fused))
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

fn display_query_candidates(query: &str, fused_candidates: &[Candidate]) -> Vec<Candidate> {
    // The EXIF corpus examples describe positive observation; do not turn a negation into a match.
    if is_negated_exif_observation_query(query) {
        return Vec::new();
    }

    let candidates = filter_unsupported_network_actions(query, fused_candidates);
    display_candidates(&candidates)
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum NetworkAction {
    Allow,
    Block,
}

impl NetworkAction {
    fn opposite(self) -> Self {
        match self {
            Self::Allow => Self::Block,
            Self::Block => Self::Allow,
        }
    }
}

fn filter_unsupported_network_actions(query: &str, candidates: &[Candidate]) -> Vec<Candidate> {
    let Some(requested_action) = requested_network_action(query) else {
        return candidates.to_vec();
    };

    candidates
        .iter()
        .filter(|candidate| candidate_supports_network_action(candidate, requested_action))
        .cloned()
        .collect()
}

fn requested_network_action(query: &str) -> Option<NetworkAction> {
    let words = normalized_words(query);
    if !has_network_context(&words) {
        return None;
    }

    let mut requested_action = None;
    for (index, word) in words.iter().enumerate() {
        let Some(mut action) = network_action(word) else {
            continue;
        };

        if action_is_negated(&words, index) {
            action = action.opposite();
        }

        match requested_action {
            Some(existing) if existing != action => return None,
            Some(_) => {}
            None => requested_action = Some(action),
        }
    }

    requested_action
}

fn requests_tar_archive_extraction(query: &str) -> bool {
    let words = normalized_words(query);
    let names_tar_archive = words
        .iter()
        .any(|word| matches!(word.as_str(), "tar" | "untar"));
    let requests_extraction = words
        .iter()
        .any(|word| matches!(word.as_str(), "extract" | "unpack" | "untar"));
    let requests_negative_action = words.iter().any(|word| {
        matches!(
            word.as_str(),
            "avoid"
                | "cant"
                | "cannot"
                | "doesnt"
                | "dont"
                | "mustnt"
                | "never"
                | "no"
                | "not"
                | "shouldnt"
                | "without"
        )
    });

    names_tar_archive && requests_extraction && !requests_negative_action
}

fn candidate_supports_archive_extraction(candidate: &Candidate) -> bool {
    let description = candidate.example_description.to_ascii_lowercase();
    description.contains("extract")
        || description.contains("[x]tract")
        || description.contains("unpack")
}

fn requests_dns_cache_invalidation(query: &str) -> bool {
    const DNS_TERMS: [&str; 2] = ["dns", "resolver"];
    const CACHE_TERMS: [&str; 3] = ["cache", "caches", "cached"];
    let words = normalized_words(query);
    let names_dns_resolver = words.iter().any(|word| DNS_TERMS.contains(&word.as_str()));
    let names_cache = words
        .iter()
        .any(|word| CACHE_TERMS.contains(&word.as_str()));
    let requests_invalidation = words
        .iter()
        .any(|word| DNS_CACHE_INVALIDATION_ACTIONS.contains(&word.as_str()));

    names_dns_resolver && names_cache && requests_invalidation
}

fn requests_recursive_text_search(query: &str) -> bool {
    const SEARCH_ACTIONS: [&str; 4] = ["find", "locate", "scan", "search"];
    const SEARCH_TARGETS: [&str; 8] = [
        "directory",
        "directories",
        "file",
        "files",
        "folder",
        "folders",
        "log",
        "logs",
    ];
    const SEARCH_TERMS: [&str; 7] = [
        "pattern", "regex", "string", "strings", "text", "word", "words",
    ];
    let words = normalized_words(query);
    let requests_search = words.iter().enumerate().any(|(index, word)| {
        SEARCH_ACTIONS.contains(&word.as_str()) && !action_is_negated(&words, index)
    });
    let names_search_target = words
        .iter()
        .any(|word| SEARCH_TARGETS.contains(&word.as_str()));
    let names_search_term = words
        .iter()
        .any(|word| SEARCH_TERMS.contains(&word.as_str()));
    let requests_recursive_search = ["all", "every", "recursive", "recursively"]
        .iter()
        .any(|term| words.iter().any(|word| word.as_str() == *term));

    requests_search && names_search_target && names_search_term && requests_recursive_search
}

fn candidate_supports_recursive_text_search(candidate: &Candidate) -> bool {
    const SEARCH_ACTIONS: [&str; 4] = ["find", "match", "matching", "search"];
    const TEXT_CONTENT: [&str; 6] = ["content", "contents", "string", "strings", "text", "word"];
    let description_words = normalized_words(&candidate.example_description);
    let describes_search = description_words
        .iter()
        .any(|word| SEARCH_ACTIONS.contains(&word.as_str()));
    let describes_text_content = description_words
        .iter()
        .any(|word| TEXT_CONTENT.contains(&word.as_str()));
    let page_command = candidate
        .page_command
        .split_whitespace()
        .next()
        .unwrap_or_default()
        .to_ascii_lowercase();
    let searches_filenames_only =
        ["fd", "fdfind", "find", "locate"].contains(&page_command.as_str());

    describes_search && (describes_text_content || !searches_filenames_only)
}

fn candidate_supports_dns_cache_invalidation(candidate: &Candidate) -> bool {
    const DNS_TERMS: [&str; 4] = ["dns", "resolver", "dscacheutil", "mdnsresponder"];
    const CACHE_TERMS: [&str; 4] = ["cache", "caches", "cached", "flushcache"];
    let example_text = format!(
        "{} {}",
        candidate.example_description, candidate.example_command
    );
    let words = normalized_words(&example_text);
    let names_dns_resolver = words.iter().any(|word| DNS_TERMS.contains(&word.as_str()));
    let names_cache = words
        .iter()
        .any(|word| CACHE_TERMS.contains(&word.as_str()));
    let demonstrates_invalidation = words
        .iter()
        .any(|word| DNS_CACHE_INVALIDATION_ACTIONS.contains(&word.as_str()));

    names_dns_resolver && names_cache && demonstrates_invalidation
}

const DNS_CACHE_INVALIDATION_ACTIONS: &[&str] = &[
    "clear",
    "cleared",
    "clearing",
    "clears",
    "delete",
    "deleted",
    "deleting",
    "deletes",
    "erase",
    "erased",
    "erasing",
    "erases",
    "flush",
    "flushed",
    "flushing",
    "flushes",
    "flushcache",
    "purge",
    "purged",
    "purging",
    "purges",
    "remove",
    "removed",
    "removing",
    "removes",
    "wipe",
    "wiped",
    "wiping",
    "wipes",
];

fn candidate_supports_network_action(
    candidate: &Candidate,
    requested_action: NetworkAction,
) -> bool {
    let example_text = format!(
        "{} {}",
        candidate.example_description, candidate.example_command
    );
    let words = normalized_words(&example_text);
    if !has_network_context(&words) {
        return false;
    }

    words
        .iter()
        .any(|word| network_action(word) == Some(requested_action))
}

fn normalized_words(text: &str) -> Vec<String> {
    text.to_ascii_lowercase()
        .replace('’', "")
        .replace('\'', "")
        .split(|character: char| !character.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .map(str::to_string)
        .collect()
}

fn has_network_context(words: &[String]) -> bool {
    const NETWORK_CONTEXT: [&str; 23] = [
        "chain",
        "connection",
        "egress",
        "firewalld",
        "firewall",
        "inbound",
        "ingress",
        "ip",
        "ip6tables",
        "iptables",
        "ipv4",
        "ipv6",
        "network",
        "nft",
        "nftables",
        "outbound",
        "packet",
        "packets",
        "port",
        "pfctl",
        "rule",
        "traffic",
        "ufw",
    ];

    words
        .iter()
        .any(|word| NETWORK_CONTEXT.contains(&word.as_str()))
}

fn network_action(word: &str) -> Option<NetworkAction> {
    const ALLOW_ACTIONS: [&str; 12] = [
        "accept",
        "accepted",
        "accepting",
        "accepts",
        "allow",
        "allowed",
        "allowing",
        "allows",
        "permit",
        "permitted",
        "permitting",
        "permits",
    ];
    const BLOCK_ACTIONS: [&str; 16] = [
        "block",
        "blocked",
        "blocking",
        "blocks",
        "deny",
        "denied",
        "denies",
        "denying",
        "drop",
        "dropped",
        "dropping",
        "drops",
        "reject",
        "rejected",
        "rejecting",
        "rejects",
    ];

    if ALLOW_ACTIONS.contains(&word) {
        Some(NetworkAction::Allow)
    } else if BLOCK_ACTIONS.contains(&word) {
        Some(NetworkAction::Block)
    } else {
        None
    }
}

fn action_is_negated(words: &[String], action_index: usize) -> bool {
    const NEGATION_WORDS: [&str; 11] = [
        "avoid", "cant", "cannot", "doesnt", "dont", "mustnt", "never", "no", "not", "shouldnt",
        "without",
    ];

    let context_start = action_index.saturating_sub(3);
    let preceding_words = &words[context_start..action_index];
    let has_negation = preceding_words
        .iter()
        .any(|word| NEGATION_WORDS.contains(&word.as_str()));
    let is_not_only = preceding_words
        .windows(2)
        .any(|pair| pair[0] == "not" && pair[1] == "only");

    has_negation && !is_not_only
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

fn filter_explicit_nftables_tool(query: &str, candidates: Vec<Candidate>) -> Vec<Candidate> {
    let normalized_query = query
        .to_ascii_lowercase()
        .replace('\'', "")
        .replace('’', "");
    let query_words = normalized_query
        .split(|character: char| !character.is_ascii_alphanumeric())
        .collect::<HashSet<_>>();
    if !query_words.contains("nft") && !query_words.contains("nftables") {
        return candidates;
    }
    let comparison_or_avoidance_terms = [
        "alternative",
        "alternatives",
        "avoid",
        "cant",
        "compare",
        "comparison",
        "cannot",
        "doesnt",
        "difference",
        "dont",
        "instead",
        "isnt",
        "never",
        "not",
        "no",
        "rather",
        "versus",
        "vs",
        "without",
    ];
    let names_other_firewall_candidate = candidates
        .iter()
        .any(|candidate| candidate_tool_is_named_in_query(candidate, &query_words));
    if comparison_or_avoidance_terms
        .iter()
        .any(|term| query_words.contains(*term))
        || names_other_firewall_candidate
    {
        return candidates;
    }

    candidates
        .into_iter()
        .filter(|candidate| {
            candidate.page_command == "nft" || candidate.page_command.starts_with("nft ")
        })
        .collect()
}

fn candidate_tool_is_named_in_query(candidate: &Candidate, query_words: &HashSet<&str>) -> bool {
    if candidate.page_command == "nft" || candidate.page_command.starts_with("nft ") {
        return false;
    }

    let command_name = candidate
        .page_command
        .split_whitespace()
        .find(|word| !matches!(*word, "sudo" | "doas"))
        .and_then(|word| word.rsplit('/').next());
    command_name.is_some_and(|command| query_words.contains(command))
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
            .split_once("More information:")
            .map_or(candidate.page_description.as_str(), |(description, _)| {
                description.trim_end()
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
    use crate::bundle::BUNDLE_MANIFEST;

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
    fn rrf_uses_main_command_preferences_to_rank_core_over_niche_variants() {
        let mut niche_variant = candidate("magick-convert-example", "magick-convert");
        niche_variant.page_command = "magick-convert".to_string();
        niche_variant.dense_distance = Some(0.1);
        let mut core_command = candidate("magick-example", "magick");
        core_command.page_command = "magick".to_string();
        core_command.dense_distance = Some(0.12);

        let fused = fuse_candidates(&[], &[niche_variant, core_command]).unwrap();

        assert_eq!(
            fused
                .iter()
                .map(|candidate| candidate.page_command.as_str())
                .collect::<Vec<_>>(),
            vec!["magick", "magick-convert"]
        );
        assert!(fused[0].ranking_score > fused[1].ranking_score);
    }

    #[test]
    fn explicit_platform_query_keeps_common_core_boost_from_overtaking_target_match() {
        let mut windows_copy = candidate("windows-copy-example", "windows-copy");
        windows_copy.platform = "windows".to_string();
        windows_copy.page_command = "copy".to_string();
        windows_copy.source_path = "pages/windows/copy.md".to_string();
        windows_copy.dense_distance = Some(0.37);

        let mut common_cp = candidate("common-cp-example", "common-cp");
        common_cp.page_command = "cp".to_string();
        common_cp.dense_distance = Some(0.43);

        let explicit =
            fuse_candidates_for_query(&[], &[windows_copy.clone(), common_cp.clone()], true)
                .unwrap();
        let host_default =
            fuse_candidates_for_query(&[], &[windows_copy, common_cp], false).unwrap();

        assert_eq!(explicit[0].page_id, "windows-copy");
        assert!(explicit[0].ranking_score > WEAK_MATCH_CUTOFF);
        assert_eq!(host_default[0].page_id, "common-cp");
    }

    #[test]
    fn main_command_preference_does_not_raise_keyword_only_results_over_weak_cutoff() {
        let mut grep = candidate("grep-only", "grep");
        grep.page_command = "grep".to_string();

        let fused = fuse_candidates(&[grep], &[]).unwrap();

        assert!(fused[0].ranking_score < WEAK_MATCH_CUTOFF);
        assert!(display_candidates(&fused).is_empty());
    }

    #[test]
    fn page_agreement_displays_the_example_with_the_higher_rrf_contribution() {
        let keyword = candidate("packer-build", "packer-page");
        let mut dense = candidate("packer-format", "packer-page");
        dense.dense_distance = Some(0.3);

        let fused = fuse_candidates(&[keyword], &[dense]);
        let displayed = display_candidates(&fused.unwrap());

        assert_eq!(displayed.len(), 1);
        assert_eq!(displayed[0].example_id, "packer-format");
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
    fn explicit_nftables_requests_exclude_other_firewall_tools() {
        let query = "block traffic using nftables on Linux";
        let mut nft = candidate("nft", "nft-page");
        nft.page_command = "nft".to_string();
        nft.ranking_score = 0.49;
        let mut ufw = candidate("ufw", "ufw-page");
        ufw.page_command = "ufw deny".to_string();
        ufw.ranking_score = 0.5122;

        let filtered = filter_explicit_nftables_tool(query, vec![ufw, nft]);

        assert_eq!(filtered.len(), 1);
        assert_eq!(filtered[0].page_command, "nft");
        assert!(display_candidates(&filtered).is_empty());
    }

    #[test]
    fn display_candidates_rejects_an_explicitly_opposed_network_action() {
        let mut accepting = candidate("nft-accept", "nft-page");
        accepting.page_command = "nft".to_string();
        accepting.example_description = "Add a rule to accept all inbound traffic".to_string();
        accepting.example_command = "sudo nft add rule inet filter input accept".to_string();
        accepting.ranking_score = 0.5122;
        let mut monitoring = candidate("nft-monitor", "nft-monitor-page");
        monitoring.page_command = "nft monitor".to_string();
        monitoring.example_description = "Monitor only firewall rule updates".to_string();
        monitoring.example_command = "sudo nft monitor rules".to_string();
        monitoring.ranking_score = 0.5039;

        let displayed = display_query_candidates(
            "block network traffic using nftables",
            &[accepting, monitoring],
        );

        assert!(displayed.is_empty());
    }

    #[test]
    fn network_action_keeps_a_matching_example_when_fusion_prefers_an_opposed_one() {
        let query = "allow network traffic using a firewall";
        let mut keyword_candidates = (0..5)
            .map(|index| candidate(&format!("filler-{index}"), &format!("filler-{index}")))
            .collect::<Vec<_>>();
        let mut allowed = candidate("ufw-allow", "ufw-page");
        allowed.page_command = "ufw".to_string();
        allowed.example_description = "Allow inbound network traffic".to_string();
        allowed.example_command = "ufw allow in on eth0".to_string();
        keyword_candidates.push(allowed);

        let mut blocked = candidate("ufw-block", "ufw-page");
        blocked.page_command = "ufw".to_string();
        blocked.example_description = "Block inbound network traffic".to_string();
        blocked.example_command = "ufw deny in on eth0".to_string();
        blocked.dense_distance = Some(0.2);

        let fused = fuse_query_candidates(query, &keyword_candidates, &[blocked], false).unwrap();
        let displayed = display_query_candidates(query, &fused);

        assert_eq!(displayed.len(), 1);
        assert_eq!(displayed[0].example_id, "ufw-allow");
    }

    #[test]
    fn dns_cache_clear_only_displays_examples_that_flush_the_dns_cache() {
        let query = "clear the macOS DNS resolver cache";
        let mut massdns = candidate("massdns-resolve", "massdns-page");
        massdns.page_command = "massdns".to_string();
        massdns.page_description = "Resolve DNS records in bulk".to_string();
        massdns.example_description = "Resolve domains in quiet mode".to_string();
        massdns.example_command = "massdns -r resolvers.txt -q domains.txt".to_string();
        massdns.platform = "osx".to_string();

        let mut resolvconf = candidate("resolvconf-delete", "resolvconf-page");
        resolvconf.page_command = "resolvconf".to_string();
        resolvconf.page_description = "Manage nameserver information".to_string();
        resolvconf.example_description = "Delete a nameserver configuration record".to_string();
        resolvconf.example_command = "resolvconf -d interface.program".to_string();
        resolvconf.platform = "common".to_string();

        let unsupported = [massdns.clone(), resolvconf.clone()];
        let fused = fuse_query_candidates(query, &unsupported, &unsupported, true).unwrap();
        let displayed = display_query_candidates(query, &fused);

        assert!(displayed.is_empty());

        let mut flush_cache = candidate("dscacheutil-flush", "dscacheutil-page");
        flush_cache.page_command = "dscacheutil".to_string();
        flush_cache.example_description = "Flush the DNS resolver cache".to_string();
        flush_cache.example_command = "sudo dscacheutil -flushcache".to_string();
        flush_cache.platform = "osx".to_string();
        let fused =
            fuse_query_candidates(query, &[flush_cache.clone()], &[flush_cache], true).unwrap();
        let displayed = display_query_candidates(query, &fused);

        assert_eq!(displayed.len(), 1);
        assert_eq!(displayed[0].example_id, "dscacheutil-flush");
    }

    #[test]
    fn tar_archive_query_keeps_an_extraction_example_when_fusion_prefers_creation() {
        let query = "unpack archive backup.tar.gz into directory restore";
        let mut keyword_candidates = (0..5)
            .map(|index| candidate(&format!("filler-{index}"), &format!("filler-{index}")))
            .collect::<Vec<_>>();
        let mut extraction = candidate("tar-extract", "tar-page");
        extraction.page_command = "tar".to_string();
        extraction.example_description =
            "E[x]tract a (compressed) archive [f]ile into the target directory".to_string();
        extraction.example_command = "tar xf source.tar -C restore".to_string();
        keyword_candidates.push(extraction);

        let mut creation = candidate("tar-create", "tar-page");
        creation.page_command = "tar".to_string();
        creation.example_description =
            "[c]reate a g[z]ipped archive and write it to a [f]ile".to_string();
        creation.example_command = "tar czf backup.tar.gz source".to_string();
        creation.dense_distance = Some(0.2);

        let fused = fuse_query_candidates(query, &keyword_candidates, &[creation], false).unwrap();
        let displayed = display_query_candidates(query, &fused);

        assert_eq!(displayed.len(), 1);
        assert_eq!(displayed[0].example_id, "tar-extract");
    }

    #[test]
    fn recursive_word_search_does_not_surface_spellcheck_examples() {
        let query = "find the word failed in every .log file under this folder";
        let mut spellcheck = candidate("codespell", "codespell-page");
        spellcheck.page_command = "codespell".to_string();
        spellcheck.example_description =
            "Check for typos in all text files in the current directory, recursively".to_string();
        spellcheck.example_command = "codespell".to_string();
        spellcheck.ranking_score = 0.5122;

        let mut text_search = candidate("findstr", "findstr-page");
        text_search.page_command = "findstr".to_string();
        text_search.example_description =
            "Find one or more strings in all files recursively".to_string();
        text_search.example_command = "findstr /s \"failed\" *.log".to_string();
        text_search.ranking_score = 0.5039;

        let fused = fuse_query_candidates(
            query,
            &[spellcheck.clone(), text_search.clone()],
            &[spellcheck, text_search],
            false,
        )
        .unwrap();
        let displayed = display_query_candidates(query, &fused);

        assert_eq!(displayed.len(), 1);
        assert_eq!(displayed[0].page_command, "findstr");
    }

    #[test]
    fn display_candidates_keeps_an_example_matching_the_requested_network_action() {
        let mut dropping = candidate("nft-drop", "nft-page");
        dropping.page_command = "nft".to_string();
        dropping.example_description = "Add a rule to drop inbound packets".to_string();
        dropping.example_command = "sudo nft add rule inet filter input drop".to_string();
        dropping.ranking_score = 0.5122;

        let displayed =
            display_query_candidates("block network traffic using nftables", &[dropping]);

        assert_eq!(displayed.len(), 1);
    }

    #[test]
    fn display_candidates_rejects_a_blocking_example_when_query_requests_allowing() {
        let mut blocking = candidate("ufw-deny", "ufw-page");
        blocking.page_command = "ufw".to_string();
        blocking.example_description = "Block all inbound traffic".to_string();
        blocking.example_command = "sudo ufw deny from any to any".to_string();
        blocking.ranking_score = 0.5122;

        let displayed =
            display_query_candidates("allow network traffic using a firewall", &[blocking]);

        assert!(displayed.is_empty());
    }

    #[test]
    fn display_candidates_interprets_negated_network_action_polarity() {
        let mut accepting = candidate("nft-accept", "nft-page");
        accepting.page_command = "nft".to_string();
        accepting.example_description = "Add a rule to accept all inbound traffic".to_string();
        accepting.example_command = "sudo nft add rule inet filter input accept".to_string();
        accepting.ranking_score = 0.5122;

        let displayed =
            display_query_candidates("do not block network traffic using nftables", &[accepting]);

        assert_eq!(displayed.len(), 1);
    }

    #[test]
    fn generic_file_access_queries_do_not_trigger_network_action_filtering() {
        let mut permissions = candidate("chmod", "chmod-page");
        permissions.page_command = "chmod".to_string();
        permissions.example_description =
            "Change permissions to restrict access to a directory".to_string();
        permissions.example_command = "chmod 000 directory".to_string();
        permissions.ranking_score = 1.0;

        let displayed = display_query_candidates("block access to a directory", &[permissions]);

        assert_eq!(displayed.len(), 1);
        assert_eq!(displayed[0].page_command, "chmod");
    }

    #[test]
    fn ip_access_queries_still_trigger_network_action_filtering() {
        assert!(matches!(
            requested_network_action("allow access from an IP address"),
            Some(NetworkAction::Allow)
        ));
    }

    #[test]
    fn nftables_comparisons_keep_other_firewall_tools() {
        let mut nft = candidate("nft", "nft-page");
        nft.page_command = "nft".to_string();
        let mut ufw = candidate("ufw", "ufw-page");
        ufw.page_command = "ufw deny".to_string();

        let filtered =
            filter_explicit_nftables_tool("compare nftables with ufw on Linux", vec![ufw, nft]);

        assert_eq!(
            filtered
                .iter()
                .map(|candidate| candidate.page_command.as_str())
                .collect::<Vec<_>>(),
            vec!["ufw deny", "nft"]
        );
    }

    #[test]
    fn nftables_or_comparison_keeps_other_firewall_tools() {
        let mut nft = candidate("nft", "nft-page");
        nft.page_command = "nft".to_string();
        let mut ufw = candidate("ufw", "ufw-page");
        ufw.page_command = "ufw deny".to_string();

        let filtered = filter_explicit_nftables_tool(
            "which is better, nftables or ufw on Linux",
            vec![ufw, nft],
        );

        assert_eq!(
            filtered
                .iter()
                .map(|candidate| candidate.page_command.as_str())
                .collect::<Vec<_>>(),
            vec!["ufw deny", "nft"]
        );
    }

    #[test]
    fn nftables_difference_queries_keep_other_firewall_tools() {
        let mut nft = candidate("nft", "nft-page");
        nft.page_command = "nft".to_string();
        let mut ufw = candidate("ufw", "ufw-page");
        ufw.page_command = "ufw deny".to_string();

        let filtered = filter_explicit_nftables_tool(
            "what is the difference between nftables and ufw on Linux",
            vec![ufw, nft],
        );

        assert_eq!(
            filtered
                .iter()
                .map(|candidate| candidate.page_command.as_str())
                .collect::<Vec<_>>(),
            vec!["ufw deny", "nft"]
        );
    }

    #[test]
    fn nftables_rather_than_queries_keep_the_preferred_firewall_tool() {
        let mut nft = candidate("nft", "nft-page");
        nft.page_command = "nft".to_string();
        let mut ufw = candidate("ufw", "ufw-page");
        ufw.page_command = "ufw deny".to_string();

        let filtered = filter_explicit_nftables_tool(
            "use ufw rather than nftables to deny traffic",
            vec![ufw, nft],
        );

        assert_eq!(
            filtered
                .iter()
                .map(|candidate| candidate.page_command.as_str())
                .collect::<Vec<_>>(),
            vec!["ufw deny", "nft"]
        );
    }

    #[test]
    fn nftables_negation_keeps_other_firewall_tools() {
        let mut nft = candidate("nft", "nft-page");
        nft.page_command = "nft".to_string();
        let mut ufw = candidate("ufw", "ufw-page");
        ufw.page_command = "ufw deny".to_string();

        let filtered =
            filter_explicit_nftables_tool("don't use nftables, use ufw on Linux", vec![ufw, nft]);

        assert_eq!(
            filtered
                .iter()
                .map(|candidate| candidate.page_command.as_str())
                .collect::<Vec<_>>(),
            vec!["ufw deny", "nft"]
        );
    }

    #[test]
    fn nftables_never_use_query_keeps_other_firewall_tools() {
        let mut nft = candidate("nft", "nft-page");
        nft.page_command = "nft".to_string();
        let mut ufw = candidate("ufw", "ufw-page");
        ufw.page_command = "ufw deny".to_string();

        let filtered = filter_explicit_nftables_tool("never use nftables on Linux", vec![ufw, nft]);

        assert_eq!(
            filtered
                .iter()
                .map(|candidate| candidate.page_command.as_str())
                .collect::<Vec<_>>(),
            vec!["ufw deny", "nft"]
        );
    }

    #[test]
    fn explicit_nftables_requests_keep_nft_subcommand_pages() {
        let mut nft = candidate("nft", "nft-page");
        nft.page_command = "nft".to_string();
        let mut nft_monitor = candidate("nft-monitor", "nft-monitor-page");
        nft_monitor.page_command = "nft monitor".to_string();
        let mut ufw = candidate("ufw", "ufw-page");
        ufw.page_command = "ufw allow".to_string();

        let filtered =
            filter_explicit_nftables_tool("show nftables events", vec![nft, nft_monitor, ufw]);

        assert_eq!(
            filtered
                .iter()
                .map(|candidate| candidate.page_command.as_str())
                .collect::<Vec<_>>(),
            vec!["nft", "nft monitor"]
        );
    }

    #[test]
    fn keyword_retrieval_tries_grounded_phrases_before_the_original_query() {
        assert_eq!(
            keyword_query_texts(
                "display photo metadata",
                DenseQueryMode::IntentRulesV1,
                "common"
            ),
            vec![
                "Print the EXIF metadata for a given file".to_string(),
                "display photo metadata".to_string(),
            ]
        );
        assert_eq!(
            keyword_query_texts("display photo metadata", DenseQueryMode::Raw, "common"),
            vec!["display photo metadata".to_string()]
        );
    }

    #[test]
    fn keyword_retrieval_tries_linux_filesystem_phrase_before_the_original_query() {
        let query = "show free disk space in human-readable units";

        assert_eq!(
            keyword_query_texts(query, DenseQueryMode::IntentRulesV1, "linux"),
            vec![
                "Display all filesystems in human-readable form".to_string(),
                query.to_string(),
            ]
        );
        assert_eq!(
            keyword_query_texts(query, DenseQueryMode::IntentRulesV1, "windows"),
            vec![query.to_string()]
        );
    }

    #[test]
    fn keyword_retrieval_maps_macos_default_path_open_to_file_example_terms() {
        let query = "launch the default app for this path";

        assert_eq!(
            keyword_query_texts(query, DenseQueryMode::IntentRulesV1, "osx"),
            vec![
                "Open a file with the associated application".to_string(),
                query.to_string(),
            ]
        );
        assert_eq!(
            keyword_query_texts(query, DenseQueryMode::Raw, "osx"),
            vec![query.to_string()]
        );
    }

    #[test]
    fn exif_removal_queries_do_not_bias_keyword_search_to_read_examples() {
        for query in [
            "remove EXIF metadata from a photo",
            "do not read EXIF metadata from a photo",
        ] {
            assert_eq!(
                keyword_query_texts(query, DenseQueryMode::IntentRulesV1, "common"),
                vec![query.to_string()],
                "negated EXIF intent must not add a positive-read query: {query}"
            );
        }
    }

    #[test]
    fn negated_exif_observation_abstains_without_suppressing_positive_requests() {
        let query = "do not read EXIF metadata from a photo";
        let mut negative_candidate = candidate("exiftool", "exiftool-page");
        negative_candidate.page_command = "exiftool".to_string();
        negative_candidate.ranking_score = 1.0;
        assert!(display_query_candidates(query, &[negative_candidate]).is_empty());

        let mut positive_candidate = candidate("exiftool", "exiftool-page");
        positive_candidate.page_command = "exiftool".to_string();
        positive_candidate.ranking_score = 1.0;
        assert_eq!(
            display_query_candidates("read EXIF metadata from a photo", &[positive_candidate])
                .len(),
            1
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
        result.page_description = "Copy files.\nMore information: https://example.test".to_string();
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
            platform_explicit: true,
            verbose: false,
        })
        .unwrap_err()
        .to_string();

        assert!(error.contains("failed to resolve matching bundle"));
    }

    #[test]
    fn candidate_fails_closed_when_bundle_manifest_is_corrupt() {
        let root = tempfile::tempdir().unwrap();
        std::fs::write(root.path().join(BUNDLE_MANIFEST), b"{not json").unwrap();

        let error = run_candidate(CandidateOptions {
            bundle: root.path().to_path_buf(),
            query: "search files".to_string(),
            target_os: TargetOs::Linux,
            platform_explicit: true,
            verbose: false,
        })
        .unwrap_err()
        .to_string();

        assert!(error.contains("failed to parse matching bundle manifest"));
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
