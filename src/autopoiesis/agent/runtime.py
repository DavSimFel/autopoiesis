"""Agent construction and process runtime state for CLI chat.

Dependencies: approval.keys, approval.policy, approval.store,
    model_resolution, models, store.subscriptions, toolset_builder
Wired in: chat.py → main()
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import AbstractToolset, Agent
from pydantic_ai._agent_graph import HistoryProcessor
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolsPrepareFunc

from autopoiesis.agent.model_resolution import build_model_settings, resolve_model
from autopoiesis.infra.approval.keys import ApprovalKeyManager
from autopoiesis.infra.approval.policy import ToolPolicyRegistry
from autopoiesis.infra.approval.store import ApprovalStore
from autopoiesis.models import AgentDeps
from autopoiesis.store.subscriptions import SubscriptionRegistry
from autopoiesis.tools.toolset_builder import LocalBackend, strict_tool_definitions


@dataclass
class Runtime:
    """Initialized runtime dependencies shared by workers and CLI."""

    agent: Agent[AgentDeps, str]
    agent_name: str
    backend: LocalBackend
    history_db_path: str
    knowledge_db_path: str
    subscription_registry: SubscriptionRegistry | None
    approval_store: ApprovalStore
    key_manager: ApprovalKeyManager
    tool_policy: ToolPolicyRegistry
    approval_unlocked: bool = False
    shell_tier: str = "review"
    """Shell approval tier from AgentConfig (free|review|approve)."""
    knowledge_root: Path | None = None
    """Absolute path to the knowledge directory; used for conversation logging."""
    log_conversations: bool = True
    """When ``True``, conversation turns are appended to daily markdown logs."""
    conversation_log_retention_days: int = 30
    """Retain conversation log files for this many days; 0 disables rotation."""


@dataclass
class AgentOptions:
    """Optional behavioural knobs for :func:`build_agent`."""

    instructions: list[str] | None = None
    history_processors: Sequence[HistoryProcessor[AgentDeps]] = ()
    model_settings: ModelSettings | None = None


class AgentRegistry:
    """Thread-safe registry mapping agent_id to Runtime.

    Backward-compatible: set()/get() without agent_id still work.
    Multi-agent: register()/get(agent_id) for per-agent isolation.
    """

    _DEFAULT_KEY: str = "__default__"

    def __init__(self) -> None:
        self._runtimes: dict[str, Runtime] = {}
        self._lock = threading.Lock()

    # --- Primary multi-agent API ---

    def register(self, agent_id: str, runtime: Runtime) -> None:
        """Register *runtime* under *agent_id*, replacing any existing entry."""
        with self._lock:
            self._runtimes[agent_id] = runtime

    def get(self, agent_id: str | None = None) -> Runtime:
        """Return the :class:`Runtime` for *agent_id*.

        When *agent_id* is ``None``:

        * If exactly one runtime is registered (or only the ``"__default__"``
          sentinel is present), it is returned.
        * If multiple runtimes are registered the ``"__default__"`` entry is
          returned when present.
        * Otherwise :class:`RuntimeError` is raised.
        """
        with self._lock:
            runtimes = dict(self._runtimes)

        if agent_id is not None:
            rt = runtimes.get(agent_id)
            if rt is None:
                visible = sorted(k for k in runtimes if k != self._DEFAULT_KEY)
                registered = ", ".join(visible) if visible else "none"
                raise RuntimeError(
                    f"No runtime registered for agent '{agent_id}'. "
                    f"Registered agents: {registered}."
                )
            return rt

        # --- backward-compatible single-runtime access ---
        if not runtimes:
            raise RuntimeError("Runtime not initialised. Start the app via main().")
        if len(runtimes) == 1:
            return next(iter(runtimes.values()))
        # Multiple runtimes: return default sentinel if present.
        default = runtimes.get(self._DEFAULT_KEY)
        if default is not None:
            return default
        visible = sorted(k for k in runtimes if k != self._DEFAULT_KEY)
        raise RuntimeError(
            f"Multiple runtimes registered ({', '.join(visible)}). "
            "Call get_runtime(agent_id=...) to select one."
        )

    def reset(self, agent_id: str | None = None) -> None:
        """Clear the registry.

        When *agent_id* is given only that agent's entry is removed; when
        ``None`` the entire registry is cleared (useful for testing).
        """
        with self._lock:
            if agent_id is None:
                self._runtimes.clear()
            else:
                self._runtimes.pop(agent_id, None)

    def list_agents(self) -> list[str]:
        """Return sorted agent IDs that have registered runtimes.

        The ``"__default__"`` sentinel (used by the backward-compatible
        :meth:`set` path) is excluded from the returned list.
        """
        with self._lock:
            return sorted(k for k in self._runtimes if k != self._DEFAULT_KEY)

    # --- Backward-compatible single-runtime API ---

    def set(self, runtime: Runtime) -> None:
        """Register *runtime* under the ``"__default__"`` sentinel key.

        Preserves call-site compatibility with the old ``RuntimeRegistry.set``
        method.
        """
        self.register(self._DEFAULT_KEY, runtime)


RuntimeRegistry = AgentRegistry  #: backward-compatible alias for ``AgentRegistry``

# ---------------------------------------------------------------------------
# Process-wide registry instance
# ---------------------------------------------------------------------------

_agent_registry: AgentRegistry = AgentRegistry()

_runtime_registry: AgentRegistry = _agent_registry  # backward-compat alias


def get_runtime_registry() -> AgentRegistry:
    """Return the active agent registry (backward-compatible name)."""
    return _agent_registry


def set_runtime_registry(registry: AgentRegistry) -> AgentRegistry:
    """Replace the active registry and return the previous one (testing).

    Accepts an :class:`AgentRegistry` (or the :data:`RuntimeRegistry` alias)
    so that existing test fixtures that construct ``RuntimeRegistry()`` work
    without modification.
    """
    global _agent_registry, _runtime_registry
    previous = _agent_registry
    _agent_registry = registry
    _runtime_registry = registry
    return previous


def get_agent_registry() -> AgentRegistry:
    """Return the active agent-keyed registry.

    Preferred over :func:`get_runtime_registry` for new code that is
    explicitly multi-agent aware.
    """
    return _agent_registry


def set_agent_registry(registry: AgentRegistry) -> AgentRegistry:
    """Replace the active agent registry and return the previous one.

    Functionally identical to :func:`set_runtime_registry`; provided as a
    clearer name for new multi-agent code.
    """
    return set_runtime_registry(registry)


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------


def register_runtime(agent_id: str, runtime: Runtime) -> None:
    """Register *runtime* under *agent_id* in the process-wide registry.

    Preferred over :func:`set_runtime` for multi-agent startups where each
    agent has its own identity.  After this call,
    ``get_runtime(agent_id)`` returns *runtime*.
    """
    _agent_registry.register(agent_id, runtime)


def set_runtime(runtime: Runtime) -> None:
    """Register *runtime* under the backward-compatible ``"__default__"`` key.

    Preserved for call-sites that are not yet agent-id-aware.  Prefer
    :func:`register_runtime` when an explicit *agent_id* is available.
    """
    _agent_registry.set(runtime)


def get_runtime(agent_id: str | None = None) -> Runtime:
    """Fetch a runtime from the process-wide registry.

    When *agent_id* is supplied the runtime registered under that identifier
    is returned; a :class:`RuntimeError` is raised if the agent is unknown.
    When *agent_id* is ``None`` the legacy single-runtime behaviour applies
    (see :meth:`AgentRegistry.get` for the full resolution order).
    """
    return _agent_registry.get(agent_id)


def reset_runtime(agent_id: str | None = None) -> None:
    """Clear runtime state from the process-wide registry.

    When *agent_id* is given only that agent's entry is removed; when
    ``None`` (default) the entire registry is cleared.  Intended for
    test teardown only.
    """
    _agent_registry.reset(agent_id)


def prepare_tools_for_provider(
    provider: str,
) -> ToolsPrepareFunc[AgentDeps] | None:
    """Return provider-specific tool preparation callback."""
    if provider == "openrouter":
        return strict_tool_definitions
    return None


def build_agent(
    provider: str,
    agent_name: str,
    toolsets: list[AbstractToolset[AgentDeps]],
    system_prompt: str,
    options: AgentOptions | None = None,
    *,
    model_override: Model | str | None = None,
) -> Agent[AgentDeps, str]:
    """Create a configured agent from provider/name/toolset settings.

    When *model_override* is supplied (e.g. resolved from ``AgentConfig.model``)
    it takes precedence over the provider-based model resolution so that per-agent
    config is honoured as the source of truth.
    """
    opts = options or AgentOptions()
    model: Model | str = model_override if model_override is not None else resolve_model(provider)
    effective_settings = opts.model_settings or build_model_settings()
    prepare_tools = prepare_tools_for_provider(provider)

    return Agent(
        model,
        deps_type=AgentDeps,
        toolsets=toolsets,
        system_prompt=system_prompt,
        instructions=opts.instructions,
        history_processors=list(opts.history_processors),
        name=agent_name,
        prepare_tools=prepare_tools,
        model_settings=effective_settings,
        end_strategy="exhaustive",
    )


def instrument_agent(agent: Agent[AgentDeps, str]) -> bool:
    """Enable OpenTelemetry instrumentation on the agent if configured."""
    _ = agent  # kept for call-site readability
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    Agent.instrument_all()
    return True
