# Issue Pipeline Workflow

Standard process for implementing issues in autopoiesis.

## Pipeline Stages

### 1. Issue Creation
- **Who:** David describes the feature/fix
- **Action:** Silas creates GitHub Issue with spec, acceptance criteria, and labels

### 2. Spec Review (Subagent)
- **Who:** Review subagent
- **Action:** Reviews issue quality — clarity, completeness, edge cases, conflicts with existing code
- **Iterates** until the spec is implementation-ready

### 3. Implementation (Codex CLI)
- **Who:** Codex CLI (OpenAI)
- **Action:** Implements on feature branch (`{type}/issue-{number}-{slug}`)
- **Iterates** until CI is green (ruff, pyright strict, pytest)
- **Must follow:** AGENTS.md rules (300 line limit, 50 line functions, no suppressions)

### 4. PR Review (Subagent)
- **Who:** Review subagent
- **Action:** Reviews against AGENTS.md checklist, all 20 anti-patterns
- **Posts** review as GitHub PR comment
- **Iterates** with implementation fixes until approved

### 5. Smoke Test & Merge
- **Who:** Silas
- **Action:** Runs smoke tests, verifies E2E behavior
- **Merges** via squash merge to main, deletes branch

## Rules
- Every stage must pass before moving to the next
- CI must be green at stages 3-5
- No skipping stages — even "obvious" fixes go through review
- Subagents handle iteration loops (fix → re-check → fix)
- Silas orchestrates and has final merge authority

## Branch Naming
`{type}/issue-{number}-{slug}`
Types: feat, fix, chore, refactor, docs, test

## Commit Format
`{type}({scope}): description (#{issue})`
