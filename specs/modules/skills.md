# Module: skills

## Purpose

`src/autopoiesis/skills/skills.py` provides a filesystem-based skill system with progressive
disclosure. Skills are folders containing a `SKILL.md` with YAML frontmatter
and markdown instructions. The agent discovers skills cheaply (frontmatter
only) and loads full instructions on demand.

## Status

- **Last updated:** 2026-02-15 (Issue #9)
- **Source:** `src/autopoiesis/skills/skills.py`

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

## Models (defined in `src/autopoiesis/skills/skills.py`)

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
| `SKILLS_DIR` | No | `skills` | `chat.py:_resolve_shipped_skills_dir()` | Shipped skill path, resolves from `src/autopoiesis/cli.py` dir |
| `CUSTOM_SKILLS_DIR` | No | `skills` | `chat.py:_resolve_custom_skills_dir()` | Custom skill path, resolves inside `AGENT_WORKSPACE_ROOT` when relative |

## Invariants

- Skills cache is built once at toolset creation.
- Skill instructions are `None` until explicitly loaded.
- Cached instructions are invalidated when the SKILL.md file's mtime
  changes, so edits during a running session are picked up on next
  `load_skill` call.
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

## Observability

- All skill tools carry `metadata={"category": "skills"}` for toolset-level observability.

## Dependencies

- `pyyaml>=6.0` (90KB, zero transitive deps)
- Internal helper module: `src/autopoiesis/skills/skillmaker_tools.py`

## Shipped Skill Contract

Shipped skills live in `skills/<skill-name>/` at the repo root. Each skill
directory **must** satisfy:

1. **`SKILL.md` exists and is non-empty** — the primary skill definition file.
2. **Valid YAML frontmatter** with required fields:
   - `name` (string, non-empty) — unique skill identifier, kebab-case.
   - `description` (string) — one-line summary.
   - `metadata.version` (string) — SemVer version.
   - `metadata.tags` (list of strings) — categorisation tags.
3. **No dead internal references** — every file in the skill directory must
   exist and be readable.
4. **Parseable by the skill loader** — `discover_skills()` and
   `parse_skill_md()` must succeed without errors.
5. **Toolset registration** — `create_skills_toolset()` must succeed when
   the `skills/` directory is provided.

These invariants are enforced by `tests/test_shipped_skills.py` (Issue #163).

CI also maps shipped skill files to this spec via the `source_to_spec` check,
so any change to a shipped skill file requires this spec to be up-to-date.

## Phase 2: MCP Skill Provider (Issue #221)

New modules added for lazy-loading skills as MCP tool sets:

| File | Responsibility |
|------|---------------|
| `skills/filesystem_skill_provider.py` | `FilesystemSkillProvider` — discovers skill directories and exposes MCP tools per skill |
| `skills/skill_activator.py` | `SkillActivator` — on-demand activator that mounts/unmounts `FilesystemSkillProvider` tools to the live MCP server |
| `skills/skill_transforms.py` | Pure transformation helpers: skill-name→tool-name mapping, schema normalisation, result envelope construction |

### Key Concepts (Phase 2)

- **Lazy MCP tool mounting** — skill tool sets are only registered with the MCP
  server when the corresponding skill topic is activated (`skill_activator.activate_skill_for_topic`).
- **Tool-name namespacing** — tools are prefixed with the skill name (e.g. `skillmaker.run`) to
  avoid collisions across simultaneously active skills.
- **Pure transforms** — `skill_transforms.py` has no I/O, enabling unit testing without a running MCP server.

## Change Log

- 2026-02-21: Added Phase 2 MCP skill provider modules (`filesystem_skill_provider.py`,
  `skill_activator.py`, `skill_transforms.py`) for lazy skill-to-MCP-tool mounting. (Issue #221)
- 2026-02-17: Documented shipped skill contract, added CI spec-check
  mappings for shipped skill files, added `tests/test_shipped_skills.py`.
  (Issue #163)

- 2026-02-16: Added mtime-based cache invalidation for skill instructions.
  `load_skill` now checks SKILL.md mtime and reloads when the file has
  changed since last cache. `Skill` model gains `instructions_mtime` field.
  `_load_skill_instructions` renamed to `load_skill_instructions` (public).
  (Issue #34)
- 2026-02-15: Added dual-location skill model (shipped + custom workspace),
  deterministic precedence (custom overrides shipped), shipped `skillmaker`
  skill, and skill quality tools (`validate_skill`, `lint_skill`). (Issue #9)
- 2026-02-15: Hardened frontmatter parsing (line-delimited delimiters),
  restricted `read_skill_resource` to discovered resources, and added
  graceful invalid-resource error handling. (Issue #9)
- 2026-02-15: Initial skill system with progressive disclosure. Instructions
  callable for system prompt integration via PydanticAI `instructions`. (Issue #9)

- 2026-02-16: Code smell cleanup — improved error messages, removed defensive checks,
  narrowed exception handling, cached regex. (Issue #89)

## GitHub Skill (#227)
- github_skill.py: built-in skill for GitHub operations with taint-safe I/O
