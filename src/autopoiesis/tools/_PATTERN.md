# Adding a New Tool

Step-by-step guide for adding a tool to autopoiesis.

## 1. Create `tools/*_tools.py`

Create a new file in the `tools/` package (e.g. `tools/widget_tools.py`).

Follow this pattern (see `tools/memory_tools.py` for a real example):

```python
"""PydanticAI tool definitions for [your domain]."""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from models import AgentDeps

_WIDGET_INSTRUCTIONS = """\
## Widget tools
Description of what these tools do and when the agent should use them.
- `widget_search`: when to use it
- `widget_create`: when to use it"""


def create_widget_toolset() -> tuple[FunctionToolset[AgentDeps], str]:
    """Create widget tools and return the toolset with instructions."""
    toolset: FunctionToolset[AgentDeps] = FunctionToolset(
        docstring_format="google",
        require_parameter_descriptions=True,
    )
    meta: dict[str, str] = {"category": "widget"}

    @toolset.tool(metadata=meta)
    async def widget_search(
        ctx: RunContext[AgentDeps],
        query: str,
    ) -> str:
        """Search for widgets.

        Args:
            query: What to search for.
        """
        # Implementation here
        return "results"

    # Ensure pyright recognizes decorator-registered functions as used
    _ = (widget_search,)

    return toolset, _WIDGET_INSTRUCTIONS
```

### Key rules

- **Typed everything** — parameters, returns, `RunContext[AgentDeps]`
- **Google-style docstrings** with `Args:` section (required by `require_parameter_descriptions=True`)
- **Instruction constant** (`_WIDGET_INSTRUCTIONS`) — gets composed into the system prompt
- **Factory function** returns `tuple[FunctionToolset[AgentDeps], str]`
- **Metadata dict** with `category` key for observable wrappers
- **Assign decorated functions** to `_` to satisfy pyright unused-variable checks

## 2. Wire in `toolset_builder.py` → `build_toolsets()`

Import your factory and add it to the toolset list:

```python
# At top of toolset_builder.py
from tools.widget_tools import create_widget_toolset

# Inside build_toolsets(), after existing toolsets:
def build_toolsets(...) -> tuple[list[AbstractToolset[AgentDeps]], str]:
    ...
    widget_toolset, widget_instr = create_widget_toolset()
    toolsets.append(widget_toolset)
    prompt_fragments.append(widget_instr)
    ...
```

If your tool needs **approval** (write/mutating operations), add an approval
predicate — see `_needs_exec_approval` and `.approval_required()` in the exec
toolset for the pattern.

If your tool should be **conditionally visible** (like exec tools behind
`ENABLE_EXECUTE`), add a prepare function — see `_prepare_exec_tools` and
`.prepared()` for the pattern.

## 3. Add Tests

Create `tests/test_widget_tools.py`:

```python
"""Tests for widget tools."""

from __future__ import annotations

import pytest

# Test the underlying logic, not the PydanticAI wiring
from tools.widget_tools import create_widget_toolset


def test_widget_toolset_creation() -> None:
    toolset, instructions = create_widget_toolset()
    assert instructions  # non-empty
    # Test tool definitions exist
    # Test actual tool behavior via the backing store/logic


def test_widget_search() -> None:
    # Test the business logic directly
    ...
```

Run: `uv run pytest tests/test_widget_tools.py -x`

## 4. Update Spec

Copy `specs/_template.md` to `specs/modules/widget_tools.md` and fill in:

- **Purpose**: what the tool does
- **Source**: `widget_tools.py`
- **Key Concepts**: domain-specific terms
- **API Surface**: tool names, parameters, env vars if any
- **Functions**: public functions with signatures

## Checklist

- [ ] `*_tools.py` with typed tool functions + instruction constant
- [ ] Wired in `toolset_builder.py` → `build_toolsets()`
- [ ] Tests in `tests/test_*_tools.py` with assertions
- [ ] Spec in `specs/modules/`
- [ ] `uv run ruff check .` passes
- [ ] `uv run pyright` passes
- [ ] `uv run pytest` passes
