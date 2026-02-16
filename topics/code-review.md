---
triggers:
  - type: manual
subscriptions: []
approval: auto
enabled: true
priority: normal
---

# Code Review

## Instructions

When reviewing code:

1. **Read the diff carefully** — understand what changed and why
2. **Check architecture** — does the design make sense for the problem?
3. **Look for bugs** — edge cases, off-by-one errors, null handling, race conditions
4. **Evaluate naming** — are variables, functions, and classes clearly named?
5. **Assess test coverage** — are happy path AND edge cases tested?
6. **Check error handling** — are errors handled explicitly, not swallowed?
7. **Flag security issues** — secrets in code, injection vectors, auth gaps

## Output Format

Structure your review as:
- **Summary**: One paragraph on what the PR does
- **Concerns**: Numbered list of issues (blocking or non-blocking)
- **Suggestions**: Optional improvements
- **Verdict**: Approve / Request Changes / Block
