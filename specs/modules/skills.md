# Module: skills

## Purpose

`skills.py` provides a filesystem-based skill system with progressive
disclosure. Skills are folders containing a `SKILL.md` with YAML frontmatter
and markdown instructions. The agent discovers skills cheaply (frontmatter
only) and loads full instructions on demand.

## Status

- **Last updated:** 2026-02-15 (Issue #9)
- **Source:** `skills.py`

## Key Concepts

- **Progressive disclosure** — the agent sees only skill name + description
  until it explicitly loads the full instructions. Keeps token usage low.
- **Skill directory** — a folder scanned for `SKILL.md` files (recursive by
  default). Configured via `SKILLS_DIR` env var.
- **Resource files** — non-SKILL.md files in a skill folder, readable via
  the `read_skill_resource` tool with path traversal protection.

## Skill Directory Structure

```
skills/
├── code-review/
│   ├── SKILL.md
│   └── checklist.md
├── research/
│   ├── SKILL.md
│   └── report.md
└── git-workflow/
    └── SKILL.md
```

## SKILL.md Format

```yaml
---
name: code-review
description: Review Python code for quality and security
version: 1.0.0
tags:
  - code
  - review
author: ""
---

# Code Review Skill

Detailed instructions the agent follows when this skill is loaded...
```

## Models (defined in `skills.py`)

- `SkillDirectory(path, recursive=True)` — directory to scan
- `Skill(name, description, path, tags, version, author, resources, instructions)` —
  `instructions` is `None` until `load_skill()` is called

## Functions

### Parsing

- `parse_skill_md(content)` — split SKILL.md into `(frontmatter_dict, instructions_str)`.
  Uses `yaml.safe_load` (pyyaml). Frontmatter delimiters are line-based (`---`
  on its own line) so embedded `---` in YAML values is safe. Missing frontmatter
  returns `({}, content)`.

### Discovery

- `discover_skills(directories)` — walk directories, read frontmatter only.
  Missing dirs → empty list. Individual parse failures logged as warnings,
  never raised.

### Instructions

- `skills_instructions(cache)` — generate a system prompt fragment listing
  discovered skill names. Returns empty string if no skills found.

### Toolset

- `create_skills_toolset(directories)` → `(FunctionToolset[AgentDeps], str)`.
  Returns the toolset and an instructions string for the system prompt.
  Tools:
  - `list_skills` — formatted list of skills with name, description, version, tags
  - `load_skill(skill_name)` — load full instructions (progressive disclosure).
    Cached after first load.
  - `read_skill_resource(skill_name, resource_name)` — read a resource file.
    Only resources listed at discovery time are readable. Path traversal
    protected via `resolve()` + `is_relative_to()`.

## Environment Variables

| Var | Required | Default | Used in | Notes |
|-----|----------|---------|---------|-------|
| `SKILLS_DIR` | No | `skills` | `chat.py:_resolve_skills_dir()` | Resolves from `chat.py` dir |

## Invariants

- Skills cache is built once at toolset creation.
- Skill instructions are `None` until explicitly loaded.
- Path traversal outside skill directory is blocked.
- `read_skill_resource` only serves files listed in `Skill.resources`.
- Missing/empty skill directories produce empty results, never errors.
- `name` field in frontmatter is required — skills without it are skipped.

## Dependencies

- `pyyaml>=6.0` (90KB, zero transitive deps)

## Change Log

- 2026-02-15: Hardened frontmatter parsing (line-delimited delimiters),
  restricted `read_skill_resource` to discovered resources, and added
  graceful invalid-resource error handling. (Issue #9)
- 2026-02-15: Initial skill system with progressive disclosure. Instructions
  callable for system prompt integration via PydanticAI `instructions`. (Issue #9)
