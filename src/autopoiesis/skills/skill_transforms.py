"""FastMCP Visibility transforms for per-agent tool filtering.

Provides factory functions that produce :class:`~fastmcp.server.transforms.Visibility`
transforms to hide or reveal tools at the MCP server level.

These replace the ``ToolPolicyRegistry`` approach with composable FastMCP
transforms that can be applied per-agent, per-request, or at startup.

Usage example::

    from fastmcp import FastMCP
    from autopoiesis.skills.skill_transforms import (
        make_skill_disable_transform,
        make_allowlist_transform,
    )

    mcp = FastMCP("autopoiesis")

    # Disable a skill's tools by default (lazy loading).
    for t in make_skill_disable_transform("skillmaker"):
        mcp.add_transform(t)

    # Later, when the skill is activated:
    mcp.enable(tags={"skillmaker"})

    # Per-agent allowlist:
    for t in make_allowlist_transform(frozenset({"exec", "knowledge_search"})):
        mcp.add_transform(t)
"""

from __future__ import annotations

from fastmcp.server.transforms import Visibility


def make_skill_disable_transform(skill_name: str) -> list[Visibility]:
    """Return transforms that disable all tools tagged with *skill_name*.

    Designed for lazy loading: call at startup to hide a skill's tools until
    the skill is explicitly activated.

    Args:
        skill_name: Tag name matching the skill's tools (same as the skills/
            subdirectory name, e.g. ``"skillmaker"``).
    """
    return [Visibility(False, tags={skill_name}, components={"tool"})]


def make_skill_enable_transform(skill_name: str) -> list[Visibility]:
    """Return transforms that enable all tools tagged with *skill_name*.

    Call after :func:`make_skill_disable_transform` to make the skill's tools
    visible.  FastMCP applies transforms in order; a later enable overrides an
    earlier disable.

    Args:
        skill_name: Tag name matching the skill's tools.
    """
    return [Visibility(True, tags={skill_name}, components={"tool"})]


def make_allowlist_transform(allowed_tool_names: frozenset[str]) -> list[Visibility]:
    """Return transforms that implement a tool-name allowlist.

    First disables **all** tools, then re-enables only the named ones.
    Useful for per-agent policy where each agent has a fixed permitted set.

    Args:
        allowed_tool_names: Exact tool names (as exposed by the MCP server,
            including any namespace prefix, e.g. ``"skillmaker_validate"``).
    """
    transforms: list[Visibility] = [
        Visibility(False, match_all=True, components={"tool"}),
    ]
    if allowed_tool_names:
        transforms.append(Visibility(True, names=set(allowed_tool_names), components={"tool"}))
    return transforms


def make_tag_allowlist_transform(allowed_tags: frozenset[str]) -> list[Visibility]:
    """Return transforms that allow only tools bearing at least one of *allowed_tags*.

    Args:
        allowed_tags: A set of tag strings.  A tool is visible if it has at
            least one of these tags.
    """
    transforms: list[Visibility] = [
        Visibility(False, match_all=True, components={"tool"}),
    ]
    if allowed_tags:
        transforms.append(Visibility(True, tags=set(allowed_tags), components={"tool"}))
    return transforms
