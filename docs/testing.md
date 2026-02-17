# Testing Guide

## Running Tests

```bash
uv run pytest                              # everything
uv run pytest tests/                       # unit tests
uv run pytest tests/integration/           # integration tests
uv run pytest tests/test_knowledge.py      # single file
uv run pytest -x                           # stop on first failure
uv run pytest -k "test_startup"            # by name pattern
uv run pytest -v                           # verbose output
```

## Test Structure

```
tests/
├── conftest.py                  # shared fixtures
├── test_*.py                    # unit tests (~30 files)
└── integration/
    ├── conftest.py              # integration fixtures (server lifecycle, etc.)
    ├── test_startup.py          # S1: Startup & Serve
    ├── test_agent_isolation.py  # S2: Agent Isolation
    ├── test_history.py          # S3: History & Recovery
    ├── test_skills.py           # S4: Skill Loading
    ├── test_shell_tool.py       # S5: Shell Tool
    ├── test_command_classification.py  # S6: Command Classification
    ├── test_toolset_assembly.py # S7: Toolset Assembly
    ├── test_knowledge.py        # S8: Knowledge System
    ├── test_topic_lifecycle.py  # S9: Topic Lifecycle
    ├── test_subscriptions.py    # S10: Subscription Pipeline
    ├── test_topic_routing.py    # S11: Topic Routing
    └── test_workitem_flow.py    # S12: WorkItem 3-Tier Flow
```

## Integration Test Tiers

### Tier 1 — Foundation

| Section | Tests | Status | What it tests |
|---------|-------|--------|---------------|
| **S1: Startup & Serve** | 7 | ✅ All green | Server boots, batch mode works, health endpoint responds |
| **S2: Agent Isolation** | 6 | 3 skip | Agents can't see each other's history, workspace, or tools |
| **S3: History & Recovery** | 5 | ✅ All green | Chat state survives restarts, history checkpoint round-trips |
| **S4: Skill Loading** | 4 | ✅ All green | Skills discovered from filesystem, custom overrides shipped |

### Tier 2 — Shell & Security

| Section | Tests | Status | What it tests |
|---------|-------|--------|---------------|
| **S5: Shell Tool** | 10 | New | Single `shell(command)` interface, output capture, timeout handling |
| **S6: Command Classification** | 10 | New | Security tier assignment (FREE/REVIEW/APPROVE/BLOCK) for commands |
| **S7: Toolset Assembly** | 5 | New | All tools register correctly, no missing/duplicate registrations |

### Tier 3 — Content & Context

| Section | Tests | Status | What it tests |
|---------|-------|--------|---------------|
| **S8: Knowledge System** | 4 | ✅ All green | Write entries, FTS5 search, auto-load on relevance, delete |
| **S9: Topic Lifecycle** | 9 | ✅ All green | Activate/deactivate topics, status transitions, edge cases |
| **S10: Subscription Pipeline** | 5 | 1 skip | File and topic subscriptions fire, context injection works |

### Tier 4 — Multi-Agent Coordination

| Section | Tests | Status | What it tests |
|---------|-------|--------|---------------|
| **S11: Topic Routing** | 6 | 4 skip | WorkItems route to topic owners, owner-based triggers fire |
| **S12: WorkItem 3-Tier Flow** | 5 | All skip | Planner creates WorkItems → Coder executes → Reviewer validates |

### Current Totals

- **38 green** — passing reliably
- **13 skip** — blocked on dependencies or unmerged work
- **25 incoming** — shell/security tests (Tier 2)

## xfail and skip Conventions

### `@pytest.mark.xfail`

Marks a test for a feature that **should work but doesn't yet**. The test documents the intended behavior as a spec. When the feature is implemented and the test starts passing, pytest will notify you to remove the xfail marker.

```python
@pytest.mark.xfail(reason="WorkItem routing not yet implemented (#123)")
def test_workitem_routes_to_topic_owner():
    ...
```

### `@pytest.mark.skip`

Marks a test that **cannot run** due to an external dependency (unmerged PR, missing infrastructure, etc.).

```python
@pytest.mark.skip(reason="Blocked on shell tool PR #171")
def test_shell_command_classification():
    ...
```

**Neither should be used to hide broken code.** If a previously-passing test breaks, fix the code — don't skip the test.

## Writing New Integration Tests

### Pattern

```python
"""S8: Knowledge System — write and search."""
import pytest
from tests.integration.conftest import some_fixture

class TestKnowledgeWrite:
    """Group related tests in a class matching the section theme."""

    def test_write_and_search(self, running_server):
        """One behavior per test. Name says what it verifies."""
        # Arrange
        ...
        # Act
        result = do_something()
        # Assert
        assert result.status == "ok"
```

### Conventions

1. **One test = one behavior.** Don't test five things in one function.
2. **Use `running_server` fixture** for tests that need a live server (from `integration/conftest.py`).
3. **Class grouping** by section theme (e.g., `TestStartup`, `TestKnowledgeSearch`).
4. **Descriptive names:** `test_<what>_<expected_outcome>` — e.g., `test_search_returns_matching_entries`.
5. **Follow the test manifest** (issue #154) for section numbering and scope.

## CI

### On Every PR

All 7 CI checks run:

| Check | Command |
|-------|---------|
| lint | `uv run ruff check .` |
| format | `uv run ruff format --check .` |
| typecheck | `uv run pyright` |
| test | `uv run pytest` |
| security | Dependency + secret scanning |
| arch-check | Architecture constraint validation |
| spec-check | Spec ↔ implementation sync |

All must pass before merge.
