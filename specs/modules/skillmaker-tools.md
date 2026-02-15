# Module: skillmaker tools

## Purpose

`skillmaker_tools.py` provides reusable linting and validation logic for
`SKILL.md` files so skill quality checks are consistent across tool calls.

## Status

- **Last updated:** 2026-02-15 (Issue #9)
- **Source:** `skillmaker_tools.py`

## Key Concepts

- **Validation** checks required frontmatter/schema semantics.
- **Linting** checks style conventions inside instruction markdown.

## Architecture

- `skills.py` reads/parses skill files, then delegates quality checks to
  `skillmaker_tools.py`.
- Tool functions exposed by `skills.py`:
  - `validate_skill(skill_name)`
  - `lint_skill(skill_name)`

## API Surface

- `validate_skill_definition(skill_name, frontmatter, instructions)` → `str`
- `lint_skill_definition(skill_name, instructions)` → `str`

## Functions

- `validate_skill_definition(...)`:
  - Enforces `name`, `description`, and non-empty instructions
  - Requires provider-supported top-level key set (`name`, `description`,
    `metadata`, and optional provider fields)
  - Requires and validates `metadata.tags` and `metadata.version`
  - Requires kebab-case `name` and semver `version`
  - Requires instructions to start with a level-1 heading
- `lint_skill_definition(...)`:
  - Flags tab characters
  - Flags lines over 100 characters
  - Flags trailing whitespace
  - Flags TODO entries without issue references (`TODO(#123)`)

## Invariants & Rules

- Output is always human-readable text designed for agent tool responses.
- Validation returns `PASSED` or `FAILED`.
- Linting returns `PASSED` or `WARNINGS`.

## Dependencies

- Python standard library only (`re`, `typing`).
- Called by `skills.py`.

## Change Log

- 2026-02-15: Added shared lint/validation helpers for `skillmaker` workflow.
  (Issue #9)
