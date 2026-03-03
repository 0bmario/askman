# Core Coding Philosophy (Pragmatic and Robust)

1. **Product-Minded**: Code exists to deliver business value. Prefer shipping a working iteration over perfect abstractions, iterate, measure, then improve.
2. **Concise and purposeful**: Keep code and comments focused. Prefer self-documenting names and small functions; omit comments that restate the obvious. Still document public APIs, important invariants, and non-trivial decisions. Avoid unnecessary boilerplate unless it meaningfully improves reliability or developer experience
3. **Pragmatic**: Favor simple, built-in language features and well-understood libraries. The simplest, readable solution that satisfies requirements wins. Design orthogonally: components should do one thing well and compose cleanly.
4. **Robust**: Own the outcome. Handle edge cases, validate inputs, and fail fast with descriptive errors. Add tests for core behavior and regression cases. When needed, provide sufficient logging and metrics to diagnose issues.
