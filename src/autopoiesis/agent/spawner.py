"""Ephemeral agent spawning from template configs.

Creates new ``AgentConfig`` instances for one-off task execution, with
isolated workspace directories created via ``resolve_agent_workspace``.

Dependencies: agent.config, agent.workspace
Wired in: (future) planner agent tool
"""

from __future__ import annotations

import re

from autopoiesis.agent.config import AgentConfig
from autopoiesis.agent.workspace import resolve_agent_workspace

_UNSAFE_PATTERN = re.compile(r"[/\\]|\.\.")
_SLUG_PATTERN = re.compile(r"[^a-zA-Z0-9_-]")


def validate_agent_name(name: str) -> str:
    """Validate and slugify an agent task name.

    Raises ``ValueError`` for empty names or names containing path traversal
    sequences (``..``, ``/``, ``\\``).  Other non-alphanumeric characters
    (except ``-`` and ``_``) are replaced with ``-``.
    """
    if not name or not name.strip():
        raise ValueError("Agent task name must not be empty")
    if _UNSAFE_PATTERN.search(name):
        raise ValueError(f"Agent task name contains unsafe path characters: {name!r}")
    slugified = _SLUG_PATTERN.sub("-", name.strip())
    if not slugified or slugified == "-":
        raise ValueError(f"Agent task name produces empty slug: {name!r}")
    return slugified


def spawn_agent(template: AgentConfig, task_name: str, parent: str) -> AgentConfig:
    """Create an ephemeral agent from a template config.

    The spawned agent gets:
    - ``name`` = ``"{template.name}-{task_name}"``
    - ``ephemeral`` = ``True``
    - ``parent`` = *parent*
    - Workspace directories created on disk via :func:`resolve_agent_workspace`

    All other fields are inherited from *template*.
    """
    safe_task_name = validate_agent_name(task_name)
    spawned_name = f"{template.name}-{safe_task_name}"

    # Ensure workspace directories exist
    paths = resolve_agent_workspace(spawned_name)
    for d in (paths.workspace, paths.memory, paths.skills, paths.knowledge, paths.tmp, paths.data):
        d.mkdir(parents=True, exist_ok=True)

    return AgentConfig(
        name=spawned_name,
        role=template.role,
        model=template.model,
        tools=list(template.tools),
        shell_tier=template.shell_tier,
        system_prompt=template.system_prompt,
        ephemeral=True,
        parent=parent,
    )
