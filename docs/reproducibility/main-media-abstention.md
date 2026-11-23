# Main-based media source coverage (draft)

- Preserve main ranking/import/rendering. On macOS, abstain for recognized speech/screen requests lacking a single supporting variant in the pinned twelve-example inventory.
- Unrecognized or ambiguous wording preserves main behavior. Other platforms bypass this inventory.
- Source: tldr-pages revision `e1cb966e711d73c42d75e79834be7e4dc17264ef`, `pages/osx/say.md` and `pages/osx/screencapture.md`; exact source lines accompany each variant in `src/media_coverage.rs`.
- The parser and entailment semantics were transferred from the frozen successful abstention experiment. Scope was restricted to macOS; all 288 prior development result identities/decisions match.
- Evidence: [verification summary](main-media-abstention-verification.json). Prior development false answers 73→68, supported coverage 179/197 unchanged, success@1 117 and success@3 136 unchanged. Synthetic AI labels; command execution not verified.
- Five performance rounds (700 measured samples, 50 warmups) pass the ≤20% latency/memory limits. Worst p95 +2.81%; worst peak memory +0.67%. Cache not purged; each invocation uses a fresh process. First round briefly overlapped a test build.
- Resolved failures: accidental non-static ONNX linkage caused CLI aborts; rebuilt with shipping static-link settings. Verifier zero-unmapped assertion corrected to exact baseline equality, with mutation checks. No candidate change based on closed quality results.
- 18 library tests pass; formatting and diff checks pass.
- Build: `env ORT_PREFER_DYNAMIC_LINK=0 LIBONNXRUNTIME_NO_PKG_CONFIG=1 cargo build --locked --offline --release --bin askman`.
- **Merge blocked pending broader-source holdout:** the fixed inventory may reject a request supported by another page. Fresh blind expanded-corpus evaluation and separately authorized scoring are required. No production or broad release superiority claim.
