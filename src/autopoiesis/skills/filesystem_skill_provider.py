"""Auto-discovery of skill FastMCP servers from the skills/ directory.

Scans ``skills/*/server.py`` files and creates :class:`FileSystemProvider`
instances for each skill that provides one.  Each provider is added to the
parent MCP server under its skill-name namespace so tools are addressable as
``{skill_name}_{tool_name}`` (e.g. ``skillmaker_validate``).

Skill server.py files should:
- Use ``@tool(tags={skill_name})`` from ``fastmcp.tools`` to register tools.
- Tag every tool with the skill directory name so Visibility transforms can
  enable/disable the whole skill as a unit.

Example skill server.py::

    from fastmcp.tools import tool

    @tool(tags={"my_skill"})
    def my_tool(arg: str) -> str:
        \"\"\"Do something.

        Args:
            arg: Description of arg.
        \"\"\"
        return f"result: {arg}"
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastmcp.server.providers.filesystem import FileSystemProvider

logger = logging.getLogger(__name__)


def discover_skill_providers(
    skills_root: Path,
) -> list[tuple[str, FileSystemProvider]]:
    """Scan ``skills/`` for subdirectories that contain a ``server.py``.

    Returns a list of ``(skill_name, provider)`` pairs.  Each provider wraps
    the skill's directory so only files in that directory are imported.

    Args:
        skills_root: Root directory to scan for skill subdirectories.
    """
    providers: list[tuple[str, FileSystemProvider]] = []

    if not skills_root.is_dir():
        logger.debug(
            "Skills root %s does not exist; no skill providers loaded",
            skills_root,
        )
        return providers

    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        server_py = skill_dir / "server.py"
        if not server_py.exists():
            continue

        skill_name = skill_dir.name
        try:
            provider = FileSystemProvider(root=skill_dir)
            providers.append((skill_name, provider))
            logger.info(
                "Loaded skill server provider: %s from %s",
                skill_name,
                server_py,
            )
        except Exception:
            logger.warning(
                "Failed to load skill server from %s",
                server_py,
                exc_info=True,
            )

    return providers


def register_skill_providers(
    mcp_server: Any,
    skills_root: Path,
) -> list[str]:
    """Discover and register skill providers on the MCP server.

    Each skill's tools are namespaced under ``{skill_name}_`` and (if the
    server.py tags its tools with the skill name) can be toggled as a group
    with :meth:`~fastmcp.FastMCP.enable` / :meth:`~fastmcp.FastMCP.disable`.

    Returns the list of skill names that were successfully registered.

    Args:
        mcp_server: A :class:`~fastmcp.FastMCP` server instance (or anything
            that implements ``add_provider(provider, namespace=...)``).
        skills_root: Root directory to scan for skill subdirectories.
    """
    registered: list[str] = []

    for skill_name, provider in discover_skill_providers(skills_root):
        try:
            mcp_server.add_provider(provider, namespace=skill_name)
            registered.append(skill_name)
        except Exception:
            logger.warning(
                "Failed to register skill provider '%s' on MCP server",
                skill_name,
                exc_info=True,
            )

    return registered
