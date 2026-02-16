"""Tests for strict_tool_definitions prepare callback."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from pydantic_ai.tools import ToolDefinition

from toolset_builder import strict_tool_definitions


def _make_tool(name: str, *, strict: bool | None = None) -> ToolDefinition:
    return ToolDefinition(name=name, description=f"{name} tool", strict=strict)


def test_strict_sets_true_on_all_tools() -> None:
    """Every returned ToolDefinition must have strict=True."""
    defs = [_make_tool("alpha"), _make_tool("beta", strict=False), _make_tool("gamma", strict=None)]
    ctx: MagicMock = MagicMock()
    result = asyncio.run(strict_tool_definitions(ctx, defs))
    assert result is not None
    expected_count = 3
    assert len(result) == expected_count
    for td in result:
        assert td.strict is True, f"{td.name} should have strict=True"


def test_strict_preserves_other_fields() -> None:
    """Fields other than strict must remain unchanged."""
    original = _make_tool("echo")
    ctx: MagicMock = MagicMock()
    result = asyncio.run(strict_tool_definitions(ctx, [original]))
    assert result is not None
    td = result[0]
    assert td.name == "echo"
    assert td.description == "echo tool"


def test_strict_empty_list() -> None:
    """An empty tool list should return an empty list (not None)."""
    ctx: MagicMock = MagicMock()
    result = asyncio.run(strict_tool_definitions(ctx, []))
    assert result is not None
    assert result == []
