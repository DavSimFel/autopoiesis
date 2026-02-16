"""Agent construction and process runtime state for CLI chat."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic_ai import AbstractToolset, Agent
from pydantic_ai._agent_graph import HistoryProcessor
from pydantic_ai.settings import ModelSettings

from approval_keys import ApprovalKeyManager
from approval_policy import ToolPolicyRegistry
from approval_store import ApprovalStore
from model_resolution import build_model_settings, resolve_model
from models import AgentDeps
from subscriptions import SubscriptionRegistry
from toolset_builder import LocalBackend, strict_tool_definitions


@dataclass
class Runtime:
    """Initialized runtime dependencies shared by workers and CLI."""

    agent: Agent[AgentDeps, str]
    backend: LocalBackend
    history_db_path: str
    memory_db_path: str
    subscription_registry: SubscriptionRegistry | None
    approval_store: ApprovalStore
    key_manager: ApprovalKeyManager
    tool_policy: ToolPolicyRegistry


@dataclass
class AgentOptions:
    """Optional behavioural knobs for :func:`build_agent`."""

    instructions: list[str] | None = None
    history_processors: Sequence[HistoryProcessor[AgentDeps]] = ()
    model_settings: ModelSettings | None = None


_runtime: Runtime | None = None


def set_runtime(runtime: Runtime) -> None:
    """Set process-wide runtime after startup wiring is complete."""
    global _runtime
    _runtime = runtime


def get_runtime() -> Runtime:
    """Fetch process-wide runtime or raise when uninitialized."""
    if _runtime is None:
        raise RuntimeError("Runtime not initialised. Start the app via main().")
    return _runtime


def build_agent(
    provider: str,
    agent_name: str,
    toolsets: list[AbstractToolset[AgentDeps]],
    system_prompt: str,
    options: AgentOptions | None = None,
) -> Agent[AgentDeps, str]:
    """Create a configured agent from provider/name/toolset settings."""
    opts = options or AgentOptions()
    model = resolve_model(provider)
    effective_settings = opts.model_settings or build_model_settings()

    return Agent(
        model,
        deps_type=AgentDeps,
        toolsets=toolsets,
        system_prompt=system_prompt,
        instructions=opts.instructions,
        history_processors=list(opts.history_processors),
        name=agent_name,
        prepare_tools=strict_tool_definitions,
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
