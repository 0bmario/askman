use crate::dense::DenseCandidate;

// Explicit source-language rules; page overviews are not evidence for an example.
struct OperationalRule {
    requested_phrases: &'static [&'static str],
    evidence_phrases: &'static [&'static str],
}

// These small phrase rules accept only explicit query requirements. Evidence
// comes from the selected example and command, never from a page overview.
const ACTION_RULES: &[OperationalRule] = &[
    OperationalRule {
        requested_phrases: &["search", "find", "locate", "look for", "look up"],
        evidence_phrases: &[
            "search",
            "find",
            "locate",
            "grep",
            "findstr",
            "mdfind",
            "where",
            "get childitem",
        ],
    },
    OperationalRule {
        requested_phrases: &[
            "list",
            "inventory",
            "enumerate",
            "show the contents",
            "show me the contents",
            "display the contents",
        ],
        evidence_phrases: &[
            "list",
            "inventory",
            "enumerate",
            "ls",
            "dir",
            "get childitem",
            "show the contents",
            "display the contents",
        ],
    },
    OperationalRule {
        requested_phrases: &["copy", "duplicate"],
        evidence_phrases: &["copy", "duplicate", "cp", "copy item", "xcopy", "robocopy"],
    },
    OperationalRule {
        requested_phrases: &["move", "relocate"],
        evidence_phrases: &["move", "relocate", "mv", "move item"],
    },
    OperationalRule {
        requested_phrases: &["rename"],
        evidence_phrases: &["rename", "renamed", "move item"],
    },
    OperationalRule {
        requested_phrases: &["delete", "remove", "erase"],
        evidence_phrases: &["delete", "remove", "erase", "rm", "del", "remove item"],
    },
    OperationalRule {
        requested_phrases: &["sort", "order"],
        evidence_phrases: &["sort", "order", "sort object"],
    },
    OperationalRule {
        requested_phrases: &["filter", "filter output", "filter results"],
        evidence_phrases: &["filter", "filtered", "grep", "findstr", "where"],
    },
    OperationalRule {
        requested_phrases: &[
            "write standard input",
            "write stdin",
            "write input to a file",
        ],
        evidence_phrases: &[
            "write standard input",
            "write stdin",
            "standard input",
            "stdin",
            "cat",
        ],
    },
    OperationalRule {
        requested_phrases: &["replace", "edit in place", "modify the original"],
        evidence_phrases: &["replace", "edit", "modify", "in place"],
    },
    OperationalRule {
        requested_phrases: &["concatenate", "combine files", "join files"],
        evidence_phrases: &["concatenate", "combine", "join", "cat"],
    },
    OperationalRule {
        requested_phrases: &["record a screen", "screen recording", "screen video"],
        evidence_phrases: &["screen recording", "record a screen", "screen video"],
    },
    OperationalRule {
        requested_phrases: &[
            "take a screenshot",
            "capture a screenshot",
            "capture the selected window",
            "capture",
            "screenshot",
        ],
        evidence_phrases: &["screenshot", "screen capture", "capture a screen"],
    },
    OperationalRule {
        requested_phrases: &["launch", "start the app", "open the app"],
        evidence_phrases: &["launch", "open", "start"],
    },
    OperationalRule {
        requested_phrases: &["restart", "stop", "start the service", "enable the service"],
        evidence_phrases: &["restart", "stop", "start", "enable"],
    },
    OperationalRule {
        requested_phrases: &["service status", "status of", "check the status"],
        evidence_phrases: &["service status", "status of a service", "status"],
    },
    OperationalRule {
        requested_phrases: &["preview", "preview what would change"],
        evidence_phrases: &["preview", "what would change", "whatif"],
    },
    OperationalRule {
        requested_phrases: &["reveal", "show in finder", "show me where"],
        evidence_phrases: &["reveal", "show in finder", "show me where"],
    },
    OperationalRule {
        requested_phrases: &["speak", "read aloud", "say this phrase"],
        evidence_phrases: &["speak", "say", "speech", "voice"],
    },
    OperationalRule {
        requested_phrases: &[
            "disk space",
            "disk usage",
            "filesystem usage",
            "memory usage",
        ],
        evidence_phrases: &[
            "disk usage",
            "filesystem usage",
            "memory usage",
            "free space",
        ],
    },
];

const CONSTRAINT_RULES: &[OperationalRule] = &[
    OperationalRule {
        requested_phrases: &[
            "recursive",
            "recursively",
            "subdirectories",
            "nested directories",
        ],
        evidence_phrases: &[
            "recursive",
            "recursively",
            "subdirectories",
            "directory tree",
        ],
    },
    OperationalRule {
        requested_phrases: &[
            "case insensitive",
            "case-insensitive",
            "ignore case",
            "ignoring letter case",
            "regardless of letter case",
        ],
        evidence_phrases: &["case insensitive", "ignore case", "-i", "-iname"],
    },
    OperationalRule {
        requested_phrases: &["regular expression", "regex"],
        evidence_phrases: &["regular expression", "regex", "-regex"],
    },
    OperationalRule {
        requested_phrases: &[
            "literal string",
            "literal text",
            "exact string",
            "exact text",
            "punctuation literally",
        ],
        evidence_phrases: &["literal", "fixed string", "fixed strings"],
    },
    OperationalRule {
        requested_phrases: &[
            "include hidden",
            "including hidden",
            "hidden items",
            "hidden files",
            "hidden directories",
        ],
        evidence_phrases: &[
            "including hidden",
            "include hidden",
            "hidden items",
            "hidden files",
            "-hidden",
        ],
    },
    OperationalRule {
        requested_phrases: &[
            "exclude hidden",
            "excluding hidden",
            "ignore hidden",
            "skip hidden",
        ],
        evidence_phrases: &[
            "exclude hidden",
            "excluding hidden",
            "ignore hidden",
            "skip hidden",
            "non hidden",
        ],
    },
    OperationalRule {
        requested_phrases: &[
            "ascending",
            "oldest first",
            "oldest entries first",
            "chronological order",
        ],
        evidence_phrases: &["ascending", "oldest first", "chronological order"],
    },
    OperationalRule {
        requested_phrases: &["descending", "newest first", "largest first"],
        evidence_phrases: &["descending", "newest first", "largest first"],
    },
    OperationalRule {
        requested_phrases: &["numerically", "numeric order", "numerical order"],
        evidence_phrases: &["numeric", "numerically", "numerical order"],
    },
    OperationalRule {
        requested_phrases: &["unique lines", "only unique", "deduplicate"],
        evidence_phrases: &["unique", "deduplicate"],
    },
    OperationalRule {
        requested_phrases: &["human readable", "human-readable", "iec units", "mb or gb"],
        evidence_phrases: &["human readable", "iec", "mb", "gb"],
    },
    OperationalRule {
        requested_phrases: &["json"],
        evidence_phrases: &["json", "-json"],
    },
    OperationalRule {
        requested_phrases: &[
            "prompt before overwriting",
            "ask before writing",
            "confirm before overwriting",
        ],
        evidence_phrases: &[
            "prompt before overwriting",
            "ask before writing",
            "confirm before overwriting",
            "interactive mode",
        ],
    },
    OperationalRule {
        requested_phrases: &[
            "without prompting",
            "do not prompt",
            "without confirmation",
            "no confirmation",
        ],
        evidence_phrases: &[
            "do not prompt",
            "without prompting",
            "no confirmation",
            "force overwrite",
        ],
    },
    OperationalRule {
        requested_phrases: &["preserve symbolic links", "preserve symlinks"],
        evidence_phrases: &[
            "preserve symbolic links",
            "preserve symlinks",
            "symbolic links",
        ],
    },
    OperationalRule {
        requested_phrases: &[
            "preserve the full source path",
            "preserve its full path",
            "preserving the folder hierarchy",
            "create intermediate directories",
        ],
        evidence_phrases: &[
            "preserve the source path",
            "preserve path",
            "folder hierarchy",
            "intermediate directories",
            "--parents",
        ],
    },
    OperationalRule {
        requested_phrases: &[
            "stdout",
            "standard output",
            "in my terminal",
            "to the terminal",
        ],
        evidence_phrases: &["stdout", "standard output", "terminal", "print"],
    },
    OperationalRule {
        requested_phrases: &[
            "follow new messages",
            "follow them",
            "keep displaying new",
            "follow the latest",
        ],
        evidence_phrases: &["follow", "new messages", "keep displaying new"],
    },
    OperationalRule {
        requested_phrases: &["latest lines", "latest 25", "most recent lines"],
        evidence_phrases: &["latest", "most recent", "last lines"],
    },
    OperationalRule {
        requested_phrases: &[
            "read the clipboard",
            "from the clipboard",
            "clipboard to grep",
        ],
        evidence_phrases: &[
            "read the clipboard",
            "from the clipboard",
            "pbpaste",
            "clipboard as input",
        ],
    },
    OperationalRule {
        requested_phrases: &["to the clipboard", "into the clipboard", "clipboard as png"],
        evidence_phrases: &["to the clipboard", "into the clipboard", "pbcopy"],
    },
    OperationalRule {
        requested_phrases: &["selected window", "currently selected window"],
        evidence_phrases: &["selected window", "window capture", "window"],
    },
    OperationalRule {
        requested_phrases: &["png"],
        evidence_phrases: &["png"],
    },
    OperationalRule {
        requested_phrases: &["show a diff", "diff before writing", "show the differences"],
        evidence_phrases: &["diff", "differences"],
    },
    OperationalRule {
        requested_phrases: &[
            "only the names",
            "only filenames",
            "just the names",
            "no details",
            "without any headings",
        ],
        evidence_phrases: &[
            "only the names",
            "only filenames",
            "just the names",
            "no details",
            "brief",
        ],
    },
    OperationalRule {
        requested_phrases: &["brief", "short summary", "concise"],
        evidence_phrases: &["brief", "short summary", "concise"],
    },
    OperationalRule {
        requested_phrases: &[
            "only the matching substring",
            "only the match",
            "not the full matching line",
        ],
        evidence_phrases: &[
            "only the matching",
            "matched substring",
            "matching substring",
        ],
    },
    OperationalRule {
        requested_phrases: &["match count", "total match count", "number of matches"],
        evidence_phrases: &["match count", "number of matches", "total count"],
    },
    OperationalRule {
        requested_phrases: &[
            "backup copy",
            "backup of the old",
            "leave a backup",
            "with a backup",
        ],
        evidence_phrases: &[
            "backup copy",
            "backup of the old",
            "backup file",
            "with a backup",
        ],
    },
    OperationalRule {
        requested_phrases: &[
            "leave the inputs untouched",
            "inputs untouched",
            "without changing the inputs",
        ],
        evidence_phrases: &[
            "leave the inputs untouched",
            "inputs untouched",
            "without changing the inputs",
        ],
    },
    OperationalRule {
        requested_phrases: &[
            "create the directory if it does not exist",
            "create the directory if missing",
            "make the destination directory",
        ],
        evidence_phrases: &[
            "create the directory if it does not exist",
            "create the directory if missing",
            "make the destination directory",
        ],
    },
    OperationalRule {
        requested_phrases: &[
            "leave its configuration files",
            "keep its configuration files",
            "leave configuration files",
        ],
        evidence_phrases: &[
            "leave configuration files",
            "keep configuration files",
            "without removing configuration files",
        ],
    },
    OperationalRule {
        requested_phrases: &["same drive"],
        evidence_phrases: &["same drive", "same volume"],
    },
    OperationalRule {
        requested_phrases: &["in place", "in the original file", "original file itself"],
        evidence_phrases: &["in place", "in the original file", "original file itself"],
    },
    OperationalRule {
        requested_phrases: &[
            "only when it is not running",
            "only if it is not running",
            "if it is not already running",
        ],
        evidence_phrases: &[
            "only when not running",
            "only if not running",
            "if not already running",
        ],
    },
    OperationalRule {
        requested_phrases: &["line numbers", "number each line"],
        evidence_phrases: &["line numbers", "number each line", "numbered lines"],
    },
    OperationalRule {
        requested_phrases: &["colorize", "colorize the filename", "color output"],
        evidence_phrases: &["colorize", "colorized", "color output"],
    },
    OperationalRule {
        requested_phrases: &["local timezone", "local time zone"],
        evidence_phrases: &["local timezone", "local time zone"],
    },
    OperationalRule {
        requested_phrases: &["modified today", "changed today"],
        evidence_phrases: &["modified today", "changed today", "today"],
    },
    OperationalRule {
        requested_phrases: &["past seven days", "last seven days", "within seven days"],
        evidence_phrases: &["past seven days", "last seven days", "within seven days"],
    },
    OperationalRule {
        requested_phrases: &["delay", "after a delay"],
        evidence_phrases: &["after a delay", "delay"],
    },
    OperationalRule {
        requested_phrases: &["frames per second", "fps"],
        evidence_phrases: &["frames per second", "fps"],
    },
    OperationalRule {
        requested_phrases: &["audio track", "with audio", "audio"],
        evidence_phrases: &["audio track", "with audio", "audio"],
    },
    OperationalRule {
        requested_phrases: &["mouse cursor", "cursor"],
        evidence_phrases: &["mouse cursor", "cursor"],
    },
    OperationalRule {
        requested_phrases: &["first ten", "first 10", "first few"],
        evidence_phrases: &["first ten", "first 10", "first", "head"],
    },
    OperationalRule {
        requested_phrases: &["speak rate", "speaking rate", "rate"],
        evidence_phrases: &["speaking rate", "rate"],
    },
    OperationalRule {
        requested_phrases: &["iec units", "iec"],
        evidence_phrases: &["iec", "base 2", "power of 2"],
    },
    OperationalRule {
        requested_phrases: &["current directory", "current folder"],
        evidence_phrases: &["current directory", "current folder"],
    },
    OperationalRule {
        requested_phrases: &["from the current folder", "under the current folder"],
        evidence_phrases: &["current directory", "current folder"],
    },
    OperationalRule {
        requested_phrases: &["directory itself", "folder itself"],
        evidence_phrases: &["directory itself", "folder itself"],
    },
    OperationalRule {
        requested_phrases: &[
            "if that destination name does not exist",
            "destination does not exist",
            "only if the file does not already exist",
            "if it does not already exist",
        ],
        evidence_phrases: &[
            "if the destination does not exist",
            "if it does not already exist",
            "does not already exist",
        ],
    },
    OperationalRule {
        requested_phrases: &["atomically", "atomic creation"],
        evidence_phrases: &["atomically", "atomic creation", "atomic"],
    },
    OperationalRule {
        requested_phrases: &[
            "run a command once for each",
            "once for each matching file",
            "for each matching file",
        ],
        evidence_phrases: &["once for each", "for each matching file", "per file"],
    },
    OperationalRule {
        requested_phrases: &[
            "redact ip addresses",
            "redacts ip addresses",
            "redact addresses",
        ],
        evidence_phrases: &[
            "redact ip addresses",
            "redacts ip addresses",
            "redact addresses",
        ],
    },
    OperationalRule {
        requested_phrases: &["bundle identifier", "bundle id"],
        evidence_phrases: &["bundle identifier", "bundle id"],
    },
    OperationalRule {
        requested_phrases: &[
            "greater than",
            "larger than",
            "above 90 percent",
            "above 90%",
            "over 90 percent",
            "over 90%",
        ],
        evidence_phrases: &["greater than", "larger than", "above", "over"],
    },
    OperationalRule {
        requested_phrases: &[
            "running service depends",
            "service depends on it",
            "services would be affected",
        ],
        evidence_phrases: &[
            "service depends",
            "services would be affected",
            "dependencies",
        ],
    },
];

pub(crate) fn example_fits_query(query: &str, candidate: &DenseCandidate) -> bool {
    unsupported_fraction(query, candidate) == 0.0
}

pub(crate) fn unsupported_fraction(query: &str, candidate: &DenseCandidate) -> f64 {
    let query_tokens = operational_tokens(query);
    let example_evidence = format!(
        "{} {} {}",
        candidate.page_command, candidate.example_description, candidate.command
    );
    let evidence_tokens = operational_tokens(&example_evidence);
    let required_rules: Vec<_> = ACTION_RULES
        .iter()
        .chain(CONSTRAINT_RULES)
        .filter(|rule| rule_is_required(&query_tokens, rule))
        .collect();
    if required_rules.is_empty() {
        return 0.0;
    }

    let unsupported_count = required_rules
        .iter()
        .filter(|rule| !has_any_phrase(&evidence_tokens, rule.evidence_phrases))
        .count();
    unsupported_count as f64 / required_rules.len() as f64
}

fn rule_is_required(tokens: &[String], rule: &OperationalRule) -> bool {
    rule.requested_phrases
        .iter()
        .any(|phrase| phrase_starts(tokens, phrase).any(|start| !phrase_is_negated(tokens, start)))
}

fn has_any_phrase(tokens: &[String], phrases: &[&str]) -> bool {
    phrases
        .iter()
        .any(|phrase| phrase_starts(tokens, phrase).any(|start| !phrase_is_negated(tokens, start)))
}

fn phrase_starts<'a>(tokens: &'a [String], phrase: &str) -> impl Iterator<Item = usize> + 'a {
    let phrase_tokens = operational_tokens(phrase);
    (0..tokens.len()).filter(move |start| {
        let end = *start + phrase_tokens.len();
        end <= tokens.len() && tokens[*start..end] == phrase_tokens
    })
}

fn phrase_is_negated(tokens: &[String], phrase_start: usize) -> bool {
    let context_start = phrase_start.saturating_sub(3);
    tokens[context_start..phrase_start]
        .iter()
        .any(|token| matches!(token.as_str(), "not" | "never" | "without" | "avoid"))
}

fn operational_tokens(value: &str) -> Vec<String> {
    value
        .split(|character: char| !character.is_alphanumeric())
        .filter(|token| !token.is_empty())
        .map(str::to_ascii_lowercase)
        .collect()
}
