"""Tests for per-agent tool filtering via FastMCP Visibility transforms.

Phase 2: skill_transforms.py replaces ToolPolicyRegistry with composable
FastMCP Visibility transforms.
"""

from __future__ import annotations

import asyncio

from autopoiesis.skills.skill_transforms import (
    make_allowlist_transform,
    make_skill_disable_transform,
    make_skill_enable_transform,
    make_tag_allowlist_transform,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server_with_tagged_tools() -> object:
    """Return a FastMCP server with two tools, each tagged with one skill."""
    from fastmcp import FastMCP
    from fastmcp.tools import tool  # type: ignore[attr-defined]

    @tool(tags={"skill_a"})  # type: ignore[misc]
    def tool_a() -> str:
        """Tool from skill A."""
        return "a"

    @tool(tags={"skill_b"})  # type: ignore[misc]
    def tool_b() -> str:
        """Tool from skill B."""
        return "b"

    mcp = FastMCP("test")
    mcp.add_tool(tool_a)
    mcp.add_tool(tool_b)
    return mcp


def _tool_names(mcp: object) -> set[str]:
    tools = asyncio.run(mcp.list_tools())  # type: ignore[attr-defined]
    return {t.name for t in tools}  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# make_skill_disable_transform
# ---------------------------------------------------------------------------


class TestMakeSkillDisableTransform:
    def test_returns_list_of_visibility(self) -> None:
        from fastmcp.server.transforms import Visibility

        transforms = make_skill_disable_transform("my_skill")
        assert isinstance(transforms, list)
        assert len(transforms) >= 1
        assert all(isinstance(t, Visibility) for t in transforms)

    def test_disables_tagged_tools(self) -> None:
        mcp = _make_server_with_tagged_tools()
        for t in make_skill_disable_transform("skill_a"):
            mcp.add_transform(t)  # type: ignore[attr-defined]

        visible = _tool_names(mcp)
        assert "tool_a" not in visible
        assert "tool_b" in visible

    def test_does_not_affect_untagged_tools(self) -> None:
        from fastmcp import FastMCP
        from fastmcp.tools import tool

        @tool  # type: ignore[misc]
        def untagged() -> str:
            """An untagged tool."""
            return "untagged"

        mcp = FastMCP("test")
        mcp.add_tool(untagged)

        for t in make_skill_disable_transform("nonexistent_skill"):
            mcp.add_transform(t)

        visible = _tool_names(mcp)
        assert "untagged" in visible


# ---------------------------------------------------------------------------
# make_skill_enable_transform
# ---------------------------------------------------------------------------


class TestMakeSkillEnableTransform:
    def test_re_enables_after_disable(self) -> None:
        mcp = _make_server_with_tagged_tools()

        # Disable first
        for t in make_skill_disable_transform("skill_a"):
            mcp.add_transform(t)  # type: ignore[attr-defined]
        assert "tool_a" not in _tool_names(mcp)

        # Then re-enable
        for t in make_skill_enable_transform("skill_a"):
            mcp.add_transform(t)  # type: ignore[attr-defined]
        assert "tool_a" in _tool_names(mcp)

    def test_returns_list_of_visibility(self) -> None:
        from fastmcp.server.transforms import Visibility

        transforms = make_skill_enable_transform("skill_x")
        assert isinstance(transforms, list)
        assert all(isinstance(t, Visibility) for t in transforms)


# ---------------------------------------------------------------------------
# make_allowlist_transform
# ---------------------------------------------------------------------------


class TestMakeAllowlistTransform:
    def test_hides_non_listed_tools(self) -> None:
        mcp = _make_server_with_tagged_tools()
        for t in make_allowlist_transform(frozenset({"tool_a"})):
            mcp.add_transform(t)  # type: ignore[attr-defined]

        visible = _tool_names(mcp)
        assert "tool_a" in visible
        assert "tool_b" not in visible

    def test_empty_allowlist_hides_everything(self) -> None:
        mcp = _make_server_with_tagged_tools()
        for t in make_allowlist_transform(frozenset()):
            mcp.add_transform(t)  # type: ignore[attr-defined]

        assert _tool_names(mcp) == set()

    def test_all_listed_tools_visible(self) -> None:
        mcp = _make_server_with_tagged_tools()
        for t in make_allowlist_transform(frozenset({"tool_a", "tool_b"})):
            mcp.add_transform(t)  # type: ignore[attr-defined]

        visible = _tool_names(mcp)
        assert {"tool_a", "tool_b"} <= visible

    def test_returns_list(self) -> None:
        transforms = make_allowlist_transform(frozenset({"some_tool"}))
        assert isinstance(transforms, list)
        assert len(transforms) >= 1


# ---------------------------------------------------------------------------
# make_tag_allowlist_transform
# ---------------------------------------------------------------------------


class TestMakeTagAllowlistTransform:
    def test_allows_tools_with_matching_tag(self) -> None:
        mcp = _make_server_with_tagged_tools()
        for t in make_tag_allowlist_transform(frozenset({"skill_a"})):
            mcp.add_transform(t)  # type: ignore[attr-defined]

        visible = _tool_names(mcp)
        assert "tool_a" in visible
        assert "tool_b" not in visible

    def test_empty_tags_hides_everything(self) -> None:
        mcp = _make_server_with_tagged_tools()
        for t in make_tag_allowlist_transform(frozenset()):
            mcp.add_transform(t)  # type: ignore[attr-defined]

        assert _tool_names(mcp) == set()

    def test_multiple_tags_are_or_logic(self) -> None:
        mcp = _make_server_with_tagged_tools()
        for t in make_tag_allowlist_transform(frozenset({"skill_a", "skill_b"})):
            mcp.add_transform(t)  # type: ignore[attr-defined]

        visible = _tool_names(mcp)
        assert "tool_a" in visible
        assert "tool_b" in visible


# ---------------------------------------------------------------------------
# Integration: disable at startup, enable later (lazy loading pattern)
# ---------------------------------------------------------------------------


class TestLazyLoadingPattern:
    def test_disable_at_startup_enable_on_activation(self) -> None:
        """Simulate the lazy-loading lifecycle."""
        mcp = _make_server_with_tagged_tools()

        # Startup: disable skill_a by default
        for t in make_skill_disable_transform("skill_a"):
            mcp.add_transform(t)  # type: ignore[attr-defined]

        assert "tool_a" not in _tool_names(mcp), "tool_a should be hidden at startup"
        assert "tool_b" in _tool_names(mcp), "tool_b should be unaffected"

        # Activation: user/topic enables skill_a
        for t in make_skill_enable_transform("skill_a"):
            mcp.add_transform(t)  # type: ignore[attr-defined]

        assert "tool_a" in _tool_names(mcp), "tool_a should be visible after activation"

    def test_disable_after_enable(self) -> None:
        """Re-disable a skill after enabling it."""
        mcp = _make_server_with_tagged_tools()

        for t in make_skill_enable_transform("skill_a"):
            mcp.add_transform(t)  # type: ignore[attr-defined]
        assert "tool_a" in _tool_names(mcp)

        for t in make_skill_disable_transform("skill_a"):
            mcp.add_transform(t)  # type: ignore[attr-defined]
        assert "tool_a" not in _tool_names(mcp)
