"""Agent configuration loading and TOML parsing.

Each agent is described by an ``AgentConfig`` dataclass.  Configs can come from
an ``agents.toml`` file (multi-agent) or be synthesized at runtime (spawning).
When no config file exists, a single ``"default"`` agent is returned for
backward compatibility.

Dependencies: (none — leaf module)
Wired in: cli.py → main(), agent/spawner.py
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from autopoiesis.agent.validation import validate_slug


@dataclass(frozen=True)
class AgentConfig:
    """Immutable description of a single agent identity."""

    name: str
    """Unique agent name, e.g. ``"planner"`` or ``"executor-fix-123"``."""

    role: str
    """One of ``"proxy"``, ``"planner"``, ``"executor"``."""

    model: str
    """Model identifier, e.g. ``"anthropic/claude-sonnet-4"``."""

    tools: list[str]
    """Tool names this agent may use."""

    shell_tier: str
    """Shell approval tier: ``"free"`` | ``"review"`` | ``"approve"``."""

    system_prompt: Path
    """Relative path to the system prompt markdown file."""

    ephemeral: bool = False
    """Ephemeral agents are destroyed after their task completes."""

    parent: str | None = None
    """Name of the parent agent that spawned this one (if any)."""

    log_conversations: bool = True
    """When ``True``, conversation turns are appended to daily markdown log
    files under ``knowledge/logs/{agent_id}/YYYY-MM-DD.md`` and indexed
    into the FTS5 knowledge system so that T2 agents can search them."""

    conversation_log_retention_days: int = 30
    """Number of days to retain conversation log files before rotation
    removes them.  Set to ``0`` to disable automatic cleanup."""

    tmp_retention_days: int = 14
    """Days to keep date-directories under ``tmp/`` before deletion."""

    tmp_max_size_mb: int = 500
    """Maximum total size of ``tmp/`` in MB; oldest dirs purged when exceeded."""


_DEFAULT_AGENT_CONFIG = AgentConfig(
    name="default",
    role="planner",
    model="anthropic/claude-sonnet-4",
    tools=["shell", "search", "topics"],
    shell_tier="review",
    system_prompt=Path("knowledge/identity/default.md"),
)

_VALID_ROLES = frozenset({"proxy", "planner", "executor"})
_VALID_SHELL_TIERS = frozenset({"free", "review", "approve"})


def _parse_agent_entry(
    name: str,
    raw: dict[str, object],
    defaults: dict[str, object],
) -> AgentConfig:
    """Build an ``AgentConfig`` from a TOML agent section merged with defaults."""

    def _get(key: str, fallback: object = None) -> object:
        val = raw.get(key)
        if val is not None:
            return val
        val = defaults.get(key)
        return val if val is not None else fallback

    role = str(_get("role", "planner"))
    if role not in _VALID_ROLES:
        msg = f"Agent '{name}': invalid role '{role}'. Must be one of {sorted(_VALID_ROLES)}."
        raise ValueError(msg)

    shell_tier = str(_get("shell_tier", "review"))
    if shell_tier not in _VALID_SHELL_TIERS:
        msg = (
            f"Agent '{name}': invalid shell_tier '{shell_tier}'. "
            f"Must be one of {sorted(_VALID_SHELL_TIERS)}."
        )
        raise ValueError(msg)

    raw_tools = _get("tools", [])
    if not isinstance(raw_tools, list):
        msg = f"Agent '{name}': 'tools' must be a list."
        raise TypeError(msg)
    tools: list[str] = [str(t) for t in cast(list[object], raw_tools)]

    model = str(_get("model", "anthropic/claude-sonnet-4"))
    system_prompt = Path(str(_get("system_prompt", f"knowledge/identity/{name}.md")))
    ephemeral = bool(_get("ephemeral", False))
    log_conversations = bool(_get("log_conversations", True))
    conversation_log_retention_days = int(str(_get("conversation_log_retention_days", 30)))
    tmp_retention_days = int(_get("tmp_retention_days", 14))
    tmp_max_size_mb = int(_get("tmp_max_size_mb", 500))

    return AgentConfig(
        name=name,
        role=role,
        model=model,
        tools=tools,
        shell_tier=shell_tier,
        system_prompt=system_prompt,
        ephemeral=ephemeral,
        log_conversations=log_conversations,
        conversation_log_retention_days=conversation_log_retention_days,
        tmp_retention_days=tmp_retention_days,
        tmp_max_size_mb=tmp_max_size_mb,
    )


def load_agent_configs(config_path: Path) -> dict[str, AgentConfig]:
    """Load agent configurations from a TOML file.

    Returns a dict keyed by agent name.  When *config_path* does not exist,
    returns a single ``"default"`` agent for backward compatibility.
    """
    if not config_path.is_file():
        return {"default": _DEFAULT_AGENT_CONFIG}

    with config_path.open("rb") as fh:
        data = tomllib.load(fh)

    defaults_raw: dict[str, object] = {}
    raw_defaults = data.get("defaults")
    if isinstance(raw_defaults, dict):
        defaults_raw = cast(dict[str, object], raw_defaults)

    agents_raw: object = data.get("agents")
    if not isinstance(agents_raw, dict) or not agents_raw:
        return {"default": _DEFAULT_AGENT_CONFIG}

    agents_section = cast(dict[str, object], agents_raw)
    configs: dict[str, AgentConfig] = {}
    for agent_name_key, agent_val in agents_section.items():
        if not isinstance(agent_val, dict):
            continue
        validate_slug(agent_name_key)
        raw_dict = cast(dict[str, object], agent_val)
        configs[agent_name_key] = _parse_agent_entry(agent_name_key, raw_dict, defaults_raw)

    if not configs:
        return {"default": _DEFAULT_AGENT_CONFIG}

    return configs
