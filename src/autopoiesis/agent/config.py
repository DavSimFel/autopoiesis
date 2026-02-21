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

    queue_poll_max_iterations: int = 900
    """Max DBOS queue-poll iterations while waiting for work item completion."""

    deferred_max_iterations: int = 10
    """Max approval deferral loop iterations for a single chat turn."""

    deferred_timeout_seconds: float = 300.0
    """Max wall-clock duration for one approval deferral loop."""

    tool_loop_max_iterations: int = 40
    """Max successful tool calls within one PydanticAI run."""

    work_item_token_budget: int = 120_000
    """Max total tokens consumed by a single work item execution."""

    work_item_timeout_seconds: float = 300.0
    """Max wall-clock duration for one work item execution."""


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


def default_agent_config() -> AgentConfig:
    """Return the built-in single-agent fallback configuration."""
    return _DEFAULT_AGENT_CONFIG


def _parse_positive_int(agent_name: str, field: str, value: object) -> int:
    """Parse a positive integer field from TOML with clear context."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        msg = f"Agent '{agent_name}': '{field}' must be a positive integer."
        raise TypeError(msg)
    return value


def _parse_positive_float(agent_name: str, field: str, value: object) -> float:
    """Parse a positive float field from TOML with clear context."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"Agent '{agent_name}': '{field}' must be a positive number."
        raise TypeError(msg)
    numeric = float(value)
    if numeric <= 0:
        msg = f"Agent '{agent_name}': '{field}' must be greater than zero."
        raise ValueError(msg)
    return numeric


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
    queue_poll_max_iterations = _parse_positive_int(
        name,
        "queue_poll_max_iterations",
        _get("queue_poll_max_iterations", 900),
    )
    deferred_max_iterations = _parse_positive_int(
        name,
        "deferred_max_iterations",
        _get("deferred_max_iterations", 10),
    )
    deferred_timeout_seconds = _parse_positive_float(
        name,
        "deferred_timeout_seconds",
        _get("deferred_timeout_seconds", 300.0),
    )
    tool_loop_max_iterations = _parse_positive_int(
        name,
        "tool_loop_max_iterations",
        _get("tool_loop_max_iterations", 40),
    )
    work_item_token_budget = _parse_positive_int(
        name,
        "work_item_token_budget",
        _get("work_item_token_budget", 120_000),
    )
    work_item_timeout_seconds = _parse_positive_float(
        name,
        "work_item_timeout_seconds",
        _get("work_item_timeout_seconds", 300.0),
    )

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
        queue_poll_max_iterations=queue_poll_max_iterations,
        deferred_max_iterations=deferred_max_iterations,
        deferred_timeout_seconds=deferred_timeout_seconds,
        tool_loop_max_iterations=tool_loop_max_iterations,
        work_item_token_budget=work_item_token_budget,
        work_item_timeout_seconds=work_item_timeout_seconds,
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
