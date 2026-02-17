"""Ephemeral agent spawning from template configs.

Creates new ``AgentConfig`` instances for one-off task execution, with
isolated workspace directories created via ``resolve_agent_workspace``.

Dependencies: agent.config, agent.workspace
Wired in: (future) planner agent tool
"""

from __future__ import annotations

from autopoiesis.agent.config import AgentConfig
from autopoiesis.agent.workspace import resolve_agent_workspace


def spawn_agent(template: AgentConfig, task_name: str, parent: str) -> AgentConfig:
    """Create an ephemeral agent from a template config.

    The spawned agent gets:
    - ``name`` = ``"{template.name}-{task_name}"``
    - ``ephemeral`` = ``True``
    - ``parent`` = *parent*
    - Workspace directories created on disk via :func:`resolve_agent_workspace`

    All other fields are inherited from *template*.
    """
    spawned_name = f"{template.name}-{task_name}"

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
