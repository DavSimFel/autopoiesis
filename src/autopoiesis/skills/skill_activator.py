"""Skill activation: enable/disable FastMCP tools when skills are activated.

:class:`SkillActivator` tracks which skills are currently enabled on a FastMCP
server and toggles tool visibility using
:meth:`~fastmcp.server.providers.base.Provider.enable` /
:meth:`~fastmcp.server.providers.base.Provider.disable`.

FastMCP applies Visibility transforms in registration order; later transforms
override earlier ones.  Calling :meth:`SkillActivator.activate` appends an
``enable`` transform that overrides the startup ``disable`` from
:func:`~autopoiesis.skills.skill_transforms.make_skill_disable_transform`.

Wiring to Topics
----------------
Call :meth:`activate_skill_for_topic` from the topic activation path to
automatically enable a skill's MCP tools when the associated topic is
activated:

.. code-block:: python

    activator.activate_skill_for_topic("github")  # enables skillmaker for "github" topic
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillActivator:
    """Manage lazy loading of skill tools on a FastMCP server instance.

    Tools for each skill start hidden (disabled via a Visibility transform
    added at startup) and become visible only when explicitly activated.

    Args:
        mcp_server: A :class:`~fastmcp.FastMCP` server instance that supports
            ``enable(tags=...)`` and ``disable(tags=...)``.
        skills_root: The ``skills/`` directory that was scanned for server.py
            files.  Used to validate that a requested skill has a server.
    """

    def __init__(self, mcp_server: Any, skills_root: Path) -> None:
        self._mcp = mcp_server
        self._skills_root = skills_root
        self._active: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def activate(self, skill_name: str) -> bool:
        """Enable all MCP tools tagged with *skill_name*.

        Returns ``True`` if the skill has a ``server.py`` and its tools were
        enabled.  Returns ``False`` if the skill has no server (not an error).

        Args:
            skill_name: Name matching the ``skills/`` subdirectory and the tag
                used when declaring tools in ``server.py``.
        """
        if not self._has_server(skill_name):
            logger.debug(
                "Skill '%s' has no server.py; skipping MCP tool activation",
                skill_name,
            )
            return False

        self._mcp.enable(tags={skill_name})
        self._active.add(skill_name)
        logger.info("Enabled MCP tools for skill '%s'", skill_name)
        return True

    def deactivate(self, skill_name: str) -> bool:
        """Disable all MCP tools tagged with *skill_name*.

        Returns ``True`` if the skill was active and has been deactivated.

        Args:
            skill_name: Name of the skill to deactivate.
        """
        if skill_name not in self._active:
            logger.debug("Skill '%s' is not active; nothing to deactivate", skill_name)
            return False

        self._mcp.disable(tags={skill_name})
        self._active.discard(skill_name)
        logger.info("Disabled MCP tools for skill '%s'", skill_name)
        return True

    def activate_skill_for_topic(self, topic_name: str, skill_name: str | None = None) -> bool:
        """Activate a skill's MCP tools when a topic is activated.

        By convention, a topic named ``"github"`` maps to a skill also named
        ``"github"``.  Pass *skill_name* explicitly to override the default
        convention.

        Returns ``True`` if a matching skill was found and activated.

        Args:
            topic_name: Name of the topic being activated.
            skill_name: Override the skill name derived from *topic_name*.
        """
        resolved = skill_name if skill_name is not None else topic_name
        return self.activate(resolved)

    def is_active(self, skill_name: str) -> bool:
        """Return ``True`` if the skill's MCP tools are currently enabled.

        Args:
            skill_name: Skill name to check.
        """
        return skill_name in self._active

    @property
    def active_skills(self) -> frozenset[str]:
        """Snapshot of currently active skill names."""
        return frozenset(self._active)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _has_server(self, skill_name: str) -> bool:
        """Return True if the skill directory contains a server.py."""
        return (self._skills_root / skill_name / "server.py").exists()
