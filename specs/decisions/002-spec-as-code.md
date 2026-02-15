# ADR-002: Specs as Code

**Date:** 2026-02-15
**Status:** Accepted

## Context

The project needed durable, reviewable technical documentation that stays synchronized with implementation changes. External documentation platforms create drift because updates are detached from code review and merge workflows.

## Decision

- Keep specs in-repo as Markdown under `specs/`.
- Require spec updates in the same PR whenever behavior changes.
- Enforce synchronization with CI checks (issue #3) using repository diffs.
- Treat missing spec updates for behavioral changes as an incomplete PR.

## Consequences

Positive:
- Documentation changes are reviewed with code in one place.
- Specs are versioned, diffable, and easy for both humans and LLMs to consume.
- CI can enforce the policy without external tooling dependencies.

Tradeoffs:
- Contributors must budget time for spec maintenance on each behavior change.
- Reviewers must enforce doc quality, not just code correctness.

