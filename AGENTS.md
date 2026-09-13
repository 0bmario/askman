## Working rules

- State material assumptions; ask when unresolved ambiguity affects the intended outcome.
- Prefer the simplest solution that meets the request; no speculative features, abstractions, or configurability.
- Keep changes within requested scope; remove code your changes make unused.
- Define observable success before coding; plan verification for multi-step work.
- Verify changed behavior with targeted checks before declaring done; report relevant checks skipped or failed.

## Low cognitive load

- Use descriptive names, self-explanatory values, and familiar language features.
- Name complex conditions; prefer early returns when they reduce nesting and clarify flow.
- Prefer composition over deep inheritance; keep related behavior easy to follow.
- Design simple interfaces that hide meaningful complexity; add layers only when they make understanding easier.
- Accept some duplication when sharing code would introduce unnecessary dependencies or indirection.
- Comment on rationale, tricky behavior, or high-level intent; omit comments that merely restate code.
