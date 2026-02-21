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

from collections.abc import Sequence
from typing import Any, cast

from fastmcp.server.transforms import GetToolNext, Transform, VersionSpec, Visibility
from fastmcp.tools.tool import Tool, ToolResult
from pydantic import PrivateAttr

from autopoiesis.security.path_validator import PathValidator

_DEFAULT_PATH_ARGUMENT_NAMES = ("path", "file_path", "directory")


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


# ---------------------------------------------------------------------------
# Path validation transform
# ---------------------------------------------------------------------------


def _copy_tool_kwargs(tool: Tool) -> dict[str, Any]:
    """Build constructor kwargs for a Tool-preserving wrapper."""
    return {
        "name": tool.name,
        "version": tool.version,
        "title": tool.title,
        "description": tool.description,
        "icons": list(tool.icons) if tool.icons is not None else None,
        "tags": set(tool.tags),
        "meta": dict(tool.meta) if tool.meta is not None else None,
        "task_config": tool.task_config,
        "parameters": dict(tool.parameters),
        "output_schema": dict(tool.output_schema) if tool.output_schema is not None else None,
        "annotations": tool.annotations,
        "execution": tool.execution,
        "serializer": tool.serializer,
        "auth": tool.auth,
        "timeout": tool.timeout,
    }


def _path_argument_names(tool: Tool, candidates: tuple[str, ...]) -> tuple[str, ...]:
    """Return tool argument names that are path-like string properties."""
    raw_properties: object = tool.parameters.get("properties")
    if not isinstance(raw_properties, dict):
        return ()
    properties: dict[str, object] = cast(dict[str, object], raw_properties)
    matches: list[str] = []
    for name in candidates:
        schema: object = properties.get(name)
        if isinstance(schema, dict) and cast(dict[str, object], schema).get("type") == "string":
            matches.append(name)
    return tuple(matches)


class _PathValidatedTool(Tool):
    """Tool wrapper that validates path-like arguments before execution."""

    _delegate: Tool = PrivateAttr()
    _path_validator: PathValidator = PrivateAttr()
    _path_arguments: tuple[str, ...] = PrivateAttr(default_factory=tuple)

    @classmethod
    def wrap(
        cls,
        tool: Tool,
        *,
        path_validator: PathValidator,
        path_arguments: tuple[str, ...],
    ) -> _PathValidatedTool:
        if isinstance(tool, _PathValidatedTool):
            return tool
        wrapped = cls(**_copy_tool_kwargs(tool))
        wrapped._delegate = tool
        wrapped._path_validator = path_validator
        wrapped._path_arguments = path_arguments
        return wrapped

    def model_copy(self, **kwargs: Any) -> _PathValidatedTool:
        copied = cast(_PathValidatedTool, super().model_copy(**kwargs))
        copied._delegate = self._delegate
        copied._path_validator = self._path_validator
        copied._path_arguments = self._path_arguments
        return copied

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        validated = self._validate_arguments(arguments)
        if isinstance(validated, ToolResult):
            return validated
        return await self._delegate.run(validated)

    def _validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any] | ToolResult:
        normalized: dict[str, Any] = dict(arguments)
        for arg_name in self._path_arguments:
            value = normalized.get(arg_name)
            if not isinstance(value, str):
                continue
            try:
                resolved = self._path_validator.resolve_path(value)
            except ValueError as exc:
                return ToolResult(
                    content=f"Path validation failed for '{arg_name}': {exc}",
                    meta={"blocked": True, "reason": "path_validation", "argument": arg_name},
                )
            normalized[arg_name] = str(resolved)
        return normalized


class PathValidationTransform(Transform):
    """Validate path-like tool arguments against a PathValidator allowlist."""

    def __init__(
        self,
        *,
        path_validator: PathValidator,
        argument_names: tuple[str, ...] = _DEFAULT_PATH_ARGUMENT_NAMES,
    ) -> None:
        self._path_validator = path_validator
        self._argument_names = argument_names

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return [self._wrap_tool(tool) for tool in tools]

    async def get_tool(
        self,
        name: str,
        call_next: GetToolNext,
        *,
        version: VersionSpec | None = None,
    ) -> Tool | None:
        tool = await call_next(name, version=version)
        if tool is None:
            return None
        return self._wrap_tool(tool)

    def _wrap_tool(self, tool: Tool) -> Tool:
        path_arguments = _path_argument_names(tool, self._argument_names)
        if not path_arguments:
            return tool
        return _PathValidatedTool.wrap(
            tool,
            path_validator=self._path_validator,
            path_arguments=path_arguments,
        )
