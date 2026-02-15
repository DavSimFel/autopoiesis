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
- **Dual skill locations** — shipped skills from `SKILLS_DIR` and custom skills
  from `CUSTOM_SKILLS_DIR` (workspace-relative by default).
- **Precedence** — custom skills override shipped skills when names collide.
- **Skill directory** — a folder scanned for `SKILL.md` files (recursive by
  default).
- **Resource files** — non-SKILL.md files in a skill folder, readable via
  the `read_skill_resource` tool with path traversal protection.

## Skill Directory Structure

```
<repo>/skills/                        # shipped
└── skillmaker/
    ├── SKILL.md
    ├── skill-template.md
    └── quality-checklist.md

<AGENT_WORKSPACE_ROOT>/skills/        # custom (default)
└── your-skill/
    └── SKILL.md
```

## SKILL.md Format

```yaml
---
name: skillmaker
description: Create and maintain high-quality skills.
metadata:
  version: 1.0.0
  tags:
    - skills
    - quality
  author: ""
---

# Skillmaker

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
  returns `({}, content)`. Output is explicitly typed to avoid unknown-type
  diagnostics under strict Pylance/Pyright settings.

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
  - `validate_skill(skill_name)` — validate SKILL.md structure and metadata.
  - `lint_skill(skill_name)` — lint SKILL.md instructions for style issues.
  Validation enforces supported top-level keys and expects extensible fields
  under `metadata`.

## Environment Variables

| Var | Required | Default | Used in | Notes |
|-----|----------|---------|---------|-------|
| `SKILLS_DIR` | No | `skills` | `chat.py:_resolve_shipped_skills_dir()` | Shipped skill path, resolves from `chat.py` dir |
| `CUSTOM_SKILLS_DIR` | No | `skills` | `chat.py:_resolve_custom_skills_dir()` | Custom skill path, resolves inside `AGENT_WORKSPACE_ROOT` when relative |

## Invariants

- Skills cache is built once at toolset creation.
- Skill instructions are `None` until explicitly loaded.
- Path traversal outside skill directory is blocked.
- `read_skill_resource` only serves files listed in `Skill.resources`.
- Missing/empty skill directories produce empty results, never errors.
- `name` field in frontmatter is required — skills without it are skipped.
- Top-level frontmatter keys should remain within provider-supported schema.
- `metadata.version` and `metadata.tags` are required.
- Custom fields like `author` are expected in `metadata`.
- Directory precedence is deterministic: shipped first, custom second.
- Name collisions are resolved by last-write-wins in cache construction,
  meaning custom skills override shipped skills.

## Dependencies

- `pyyaml>=6.0` (90KB, zero transitive deps)
- Internal helper module: `skillmaker_tools.py`

## Change Log

- 2026-02-15: Added dual-location skill model (shipped + custom workspace),
  deterministic precedence (custom overrides shipped), shipped `skillmaker`
  skill, and skill quality tools (`validate_skill`, `lint_skill`). (Issue #9)
- 2026-02-15: Hardened frontmatter parsing (line-delimited delimiters),
  restricted `read_skill_resource` to discovered resources, and added
  graceful invalid-resource error handling. (Issue #9)
- 2026-02-15: Initial skill system with progressive disclosure. Instructions
  callable for system prompt integration via PydanticAI `instructions`. (Issue #9)
