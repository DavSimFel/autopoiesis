# ADR-001: Trunk-Based Workflow

**Date:** 2026-02-15
**Status:** Accepted

## Context

The project needed a clear collaboration model for fast iteration with human and agent contributors. In Issue #1, the team evaluated branch strategy, merge policy, and how to parallelize changes safely without long-lived integration branches.

For full background and rationale details, see GitHub Issue #1.

## Decision

- Use trunk-based development with `main` as the single integration branch.
- Drop the separate `dev` branch workflow.
- Keep feature branches short-lived and scoped to one change.
- Open PRs against `main` and use squash merge.
- Use git worktrees when running parallel agent efforts so each task has isolated filesystem state.

## Consequences

Positive:
- Faster integration cadence and less branch divergence.
- Simpler release path because `main` is always the source of truth.
- Cleaner history from squash merges.
- Worktrees reduce context collisions for concurrent contributors.

Tradeoffs:
- Requires tighter PR review discipline because integration happens continuously.
- Large or long-running efforts must be split into smaller PRs to avoid rebasing pain.

