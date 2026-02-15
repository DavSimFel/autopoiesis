# Contributing to Autopoiesis

## For AI Agents
Read `AGENTS.md` first; it contains project-specific instructions that override
general knowledge.

## Workflow
1. Pick up an issue (or get assigned one)
2. Create branch: `{type}/issue-{number}-{slug}` from `main`
3. Implement. Update specs. Run all checks locally.
4. Open PR to `main` using the PR template
5. Address review feedback and iterate until approved
6. Never merge your own PR

## PR Requirements
- All CI checks pass (lint, typecheck, spec sync)
- Spec files updated if behavior changed
- One logical concern per PR
- 50-200 lines changed ideal, 400 max

## Who Reviews
- AI agents review each other's PRs
- David has final approval on `main`
- Reviewers check code quality, spec alignment, test coverage, and anti-patterns

## What Gets Rejected
See Anti-Patterns in `AGENTS.md`.
