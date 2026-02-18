# Contributing to Autopoiesis

## For AI Agents

Read `AGENTS.md` first — it has project-specific rules that override general knowledge.

---

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — package manager (no pip, no poetry)
- **git**

## Setup

```bash
git clone https://github.com/DavSimFel/autopoiesis.git
cd autopoiesis
uv sync
cp .env.example .env   # set AI_PROVIDER and API keys
uv run pytest           # verify everything works
```

---

## Core Workflow: Specs and Tests

**Developer control happens through specs and tests.** Code is written by agents, verified by CI, approved by humans.

### Specs

Every module has a spec in `specs/modules/*.md`. Specs define:
- What the module does (contract)
- Public API surface
- Invariants that must hold

**When you change behavior → update the spec.** New module → create spec from `specs/_template.md`. Architecture changes → ADR in `specs/decisions/`.

CI runs `spec-check` to verify specs stay in sync with code.

### Tests

Tests are the executable version of specs. See **[docs/testing.md](docs/testing.md)** for the complete guide.

```bash
uv run pytest                          # all tests
uv run pytest tests/integration/       # integration only
uv run pytest tests/test_knowledge.py  # single file
uv run pytest -x                       # stop on first failure
uv run pytest -k "test_startup"        # by name pattern
```

### xfail and skip Conventions

- **`xfail`** = spec for an unimplemented feature. The test documents intended behavior; it's expected to fail until implemented.
- **`skip`** = blocked on an external dependency or unmerged PR. Can't run yet.

Both are legitimate. Neither should be used to hide broken code.

---

## CI Pipeline

Every PR runs 7 checks:

| Check | What it does |
|-------|-------------|
| **lint** | `ruff check .` — style and import rules |
| **format** | `ruff format --check .` — code formatting |
| **typecheck** | `pyright` — strict type checking |
| **test** | `pytest` — all tests must pass |
| **security** | Dependency and secret scanning |
| **narrative** | Checks narrative docs are current |
| **arch-check** | Validates architecture constraints |
| **spec-check** | Verifies specs match implementation |

All must be green before merge.

---

## Git Workflow

### Branch

```bash
git checkout main && git pull
git checkout -b feat/issue-42-add-widget
```

Branch format: `{type}/issue-{number}-{slug}`
Types: `feat`, `fix`, `chore`, `refactor`, `docs`

### Commit

```bash
git commit -m "feat(chat): add widget support (#42)"
```

Format: `type(scope): description (#issue)`

### PR

Push to origin, open PR to `main`. Squash merge after approval.

### Review Process

1. **Agents write code** on feature branches
2. **CI verifies** — all 7 checks must pass
3. **Human approves** — David has final say on `main`

---

## Auto-Merge Policy

PRs are subject to the following merge policy:

- **PRs that modify `tests/integration/`** are automatically labeled `needs-human-review` and require human approval before merge. Integration tests define the architecture spec and are controlled by humans.
- **All other PRs** auto-merge when CI passes.
- The `integration-test-guard` CI job detects integration test changes and posts a comment — it always passes (advisory, not blocking).

---

## Code Style Essentials

| Rule | Detail |
|------|--------|
| **Typing** | Strict pyright. Every parameter and return typed. No `Any` without justification. |
| **Naming** | `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE` constants |
| **Imports** | stdlib → third-party → local, separated by blank lines. No wildcards. |
| **Docstrings** | Google style. Required on all public functions/classes. |
| **Comments** | Explain WHY, never WHAT. No commented-out code. |
| **File limit** | 300 lines max |
| **Function limit** | 50 lines max |
| **Suppressions** | No `# noqa`, no `# type: ignore`. Fix the code. |
| **TODOs** | Must reference an issue: `# TODO(#42): description` |

## What Gets Your PR Rejected

1. Lint/type suppressions
2. Files over 300 lines or functions over 50 lines
3. Dead code, unused imports, bare `except:`
4. Missing specs for behavior changes
5. Hardcoded secrets
6. `print()` debugging (use `logging`)
7. Missing docstrings on public API
8. Mixing concerns in one PR
9. Skipping CI checks locally

---

## Project Map

| Area | Files |
|------|-------|
| Entry point | `src/autopoiesis/cli.py` |
| CLI loop | `agent/cli.py` |
| Agent builder | `agent/runtime.py` |
| Queue worker | `agent/worker.py` |
| Tool wiring | `toolset_builder.py`, `tools/toolset_wrappers.py` |
| Execution tools | `tools/exec_tool.py`, `tools/process_tool.py`, `infra/command_classifier.py` |
| Knowledge tools | `tools/knowledge_tools.py`, `store/knowledge.py` |
| Skills | `skills.py`, `skillmaker_tools.py` |
| Subscriptions | `tools/subscription_tools.py`, `store/subscriptions.py` |
| Approval | `approval/` |
| Tests | `tests/`, `tests/integration/` |
| Specs | `specs/modules/` |
