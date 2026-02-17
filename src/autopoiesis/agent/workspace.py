"""Agent identity and workspace path resolution.

Each agent gets an isolated directory tree under ``~/.autopoiesis/agents/{name}/``.
The ``resolve_agent_workspace`` function returns a structured ``AgentPaths`` object
that other modules use instead of hard-coding paths.

Dependencies: (none — leaf module)
Wired in: cli.py → main(), agent/runtime.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_AUTOPOIESIS_HOME_DEFAULT = "~/.autopoiesis"
_DEFAULT_AGENT_NAME = "default"


@dataclass(frozen=True)
class AgentPaths:
    """Resolved directory tree for a single agent identity."""

    root: Path
    """``~/.autopoiesis/agents/{name}/``"""

    workspace: Path
    """``root/workspace/``"""

    memory: Path
    """``root/workspace/memory/``"""

    skills: Path
    """``root/workspace/skills/``"""

    knowledge: Path
    """``root/workspace/knowledge/``"""

    tmp: Path
    """``root/workspace/tmp/``"""

    data: Path
    """``root/data/``"""

    keys: Path
    """``root/keys/``"""


def resolve_agent_name(cli_agent: str | None = None) -> str:
    """Determine agent name from CLI flag, env var, or default.

    Priority: *cli_agent* > ``AUTOPOIESIS_AGENT`` env var > ``"default"``.
    """
    if cli_agent:
        return cli_agent
    return os.getenv("AUTOPOIESIS_AGENT", _DEFAULT_AGENT_NAME)


def resolve_agent_workspace(agent_name: str | None = None) -> AgentPaths:
    """Build the full ``AgentPaths`` for *agent_name*.

    When *agent_name* is ``None`` the name is resolved via
    :func:`resolve_agent_name` (env var / default).
    """
    name = agent_name or resolve_agent_name()
    home = Path(os.getenv("AUTOPOIESIS_HOME", _AUTOPOIESIS_HOME_DEFAULT)).expanduser()
    root = home / "agents" / name
    workspace = root / "workspace"
    return AgentPaths(
        root=root,
        workspace=workspace,
        memory=workspace / "memory",
        skills=workspace / "skills",
        knowledge=workspace / "knowledge",
        tmp=workspace / "tmp",
        data=root / "data",
        keys=root / "keys",
    )
