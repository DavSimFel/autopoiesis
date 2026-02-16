# Contributing to Autopoiesis

## For AI Agents

Read `AGENTS.md` first — it has project-specific rules that override general
knowledge. Use the **File Map** to navigate; don't read the whole codebase.

---

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** (package manager — no pip, no poetry)
- **git**

## 5-Minute Setup

```bash
# 1. Clone and enter
git clone https://github.com/DavSimFel/autopoiesis.git
cd autopoiesis

# 2. Install dependencies
uv sync

# 3. Configure environment
cp .env.example .env
# Edit .env — set AI_PROVIDER and API keys

# 4. Verify everything works
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest

# 5. Run
uv run python chat.py
```

## Project Map

Source is organized into subdirectory packages. Root-level files handle
entry point wiring and shared utilities.

| Area | Files |
|------|-------|
| Entry point | `chat.py` |
| CLI loop | `agent/cli.py` |
| Agent builder | `agent/runtime.py` |
| Queue worker | `agent/worker.py` |
| Context mgmt | `agent/context.py`, `agent/truncation.py` |
| Tool wiring | `toolset_builder.py`, `tools/toolset_wrappers.py` |
| System prompt | `prompts.py` |
| Core types | `models.py`, `infra/work_queue.py` |
| Exec tools | `tools/exec_tool.py`, `tools/process_tool.py`, `infra/exec_registry.py`, `infra/pty_spawn.py` |
| Memory tools | `tools/memory_tools.py`, `store/memory.py` |
| Skills | `skills.py`, `skillmaker_tools.py` |
| Subscriptions | `tools/subscription_tools.py`, `store/subscriptions.py`, `infra/subscription_processor.py` |
| Approval system | `approval/` (types, crypto, keys, key_files, policy, store, chat_approval) |
| Persistence | `store/history.py`, `db.py` |
| Display | `display/streaming.py`, `display/rich_display.py`, `display/stream_formatting.py` |
| Model resolution | `model_resolution.py` |
| Observability | `infra/otel_tracing.py` |
| Specs | `specs/` (module specs, decisions, template) |
| Tests | `tests/` |

## "I Want To..." Quick Reference

| I want to... | Do this |
|---------------|---------|
| Add a new tool | Follow `tools/_PATTERN.md` |
| Change the system prompt | Edit `prompts.py`, check `toolset_builder.py` for composition |
| Add a provider | Edit `model_resolution.py` |
| Fix a test | Find matching `tests/test_*.py`, run `uv run pytest tests/test_foo.py -x` |
| Add a dependency | Edit `pyproject.toml`, run `uv sync`, get explicit approval first |
| Understand the architecture | Read `ARCHITECTURE.md` |
| Find where something lives | Use the File Map in `AGENTS.md` |

## First PR Walkthrough

### 1. Branch

```bash
git checkout main && git pull
git checkout -b feat/issue-42-add-widget
```

Branch format: `{type}/issue-{number}-{slug}`
Types: `feat`, `fix`, `chore`, `refactor`, `docs`

### 2. Implement

- Keep changes scoped to one logical concern
- Follow the code style below
- Update specs in `specs/modules/` if behavior changed
- New modules get a spec from `specs/_template.md`

### 3. Verify

```bash
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run pyright                # type checking
uv run pytest                 # tests
```

All four must pass. No exceptions.

### 4. Commit

```bash
git add -A
git commit -m "feat(chat): add widget support (#42)"
```

Format: `type(scope): description (#issue)`

### 5. Push & PR

```bash
git push -u origin feat/issue-42-add-widget
```

Open a PR to `main`. Fill in the PR template. Reference the issue.

### 6. Review

- AI agents review each other's PRs
- David has final approval on `main`
- Address all feedback before re-requesting review

## Code Style Essentials

| Rule | Detail |
|------|--------|
| **Typing** | Strict pyright. Every parameter and return typed. No `Any` without justification. |
| **Naming** | `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE` constants |
| **Imports** | stdlib → third-party → local, separated by blank lines. No wildcard imports. |
| **Docstrings** | Google style. Required on all public functions/classes. |
| **Comments** | Explain WHY, never WHAT. No commented-out code. |
| **File limit** | 300 lines max per file |
| **Function limit** | 50 lines max per function |
| **Complexity** | Max cyclomatic complexity: 10 |
| **TODOs** | Must reference an issue: `# TODO(#42): description` |
| **Suppressions** | No `# noqa`, no `# type: ignore`, no pyright ignore directives. Fix the code. |

## Spec Requirements

Every PR that changes behavior **must** update specs:

- Modified module → update its spec in `specs/modules/`
- New module → create spec from `specs/_template.md`
- Architecture change → ADR in `specs/decisions/`
- System-level change → update `specs/OVERVIEW.md`
- Always add a changelog entry with date and PR/issue number

## What Gets Your PR Rejected

1. Any lint/type suppression (`# noqa`, type-ignore, pyright ignore)
2. Weakening lint rules to make CI pass
3. Files over 300 lines
4. Functions over 50 lines
5. Dead code (commented-out blocks, unused imports)
6. TODOs without issue links
7. Bare `except:` or `except Exception:` without specific handling
8. Hardcoded secrets or environment-specific values
9. `print()` for debugging (use `logging`)
10. Untyped parameters or return values
11. Magic numbers without named constants
12. Adding deps for trivial functionality
13. Mixing concerns in one PR (feature + refactor + fix)
14. Swallowed errors (`except: pass`)
15. Copy-paste duplication
16. Missing docstrings on public functions/classes
17. Test files without assertions
18. Changes outside the scope of the issue
19. Missing spec updates for behavior changes
20. Skipping CI checks locally before pushing
