"""Agent construction and process runtime state for CLI chat."""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic_ai import AbstractToolset, Agent
from pydantic_ai._agent_graph import HistoryProcessor
from pydantic_ai.settings import ModelSettings

from approval.keys import ApprovalKeyManager
from approval.policy import ToolPolicyRegistry
from approval.store import ApprovalStore
from model_resolution import build_model_settings, resolve_model
from models import AgentDeps
from store.subscriptions import SubscriptionRegistry
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


class RuntimeRegistry:
    """Thread-safe storage for process-wide runtime dependencies."""

    def __init__(self) -> None:
        self._runtime: Runtime | None = None
        self._lock = threading.Lock()

    def set(self, runtime: Runtime) -> None:
        """Store runtime after startup wiring completes."""
        with self._lock:
            self._runtime = runtime

    def get(self) -> Runtime:
        """Return configured runtime, raising when startup has not run."""
        with self._lock:
            runtime = self._runtime
        if runtime is None:
            raise RuntimeError("Runtime not initialised. Start the app via main().")
        return runtime

    def reset(self) -> None:
        """Clear configured runtime for tests."""
        with self._lock:
            self._runtime = None


_runtime_registry = RuntimeRegistry()


def get_runtime_registry() -> RuntimeRegistry:
    """Return the active runtime registry."""
    return _runtime_registry


def set_runtime_registry(registry: RuntimeRegistry) -> RuntimeRegistry:
    """Replace the active runtime registry and return the previous one."""
    global _runtime_registry
    previous = _runtime_registry
    _runtime_registry = registry
    return previous


def set_runtime(runtime: Runtime) -> None:
    """Set process-wide runtime after startup wiring is complete."""
    _runtime_registry.set(runtime)


def get_runtime() -> Runtime:
    """Fetch process-wide runtime or raise when uninitialized."""
    return _runtime_registry.get()


def reset_runtime() -> None:
    """Clear process-wide runtime (testing only)."""
    _runtime_registry.reset()


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
