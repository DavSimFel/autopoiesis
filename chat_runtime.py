"""Runtime initialization helpers for CLI chat."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, get_type_hints

from pydantic_ai import AbstractToolset, Agent, RunContext
from pydantic_ai._agent_graph import HistoryProcessor
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition

from approval_keys import ApprovalKeyManager
from approval_policy import ToolPolicyRegistry
from approval_store import ApprovalStore
from memory_tools import create_memory_toolset
from models import AgentDeps
from prompts import (
    BASE_SYSTEM_PROMPT,
    CONSOLE_INSTRUCTIONS,
    EXEC_INSTRUCTIONS,
    compose_system_prompt,
)
from skills import SkillDirectory, create_skills_toolset
from subscription_tools import create_subscription_toolset
from subscriptions import SubscriptionRegistry
from toolset_wrappers import wrap_toolsets

try:
    from pydantic_ai_backends import LocalBackend, create_console_toolset
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing backend dependency. Run `uv sync` so `pydantic-ai-backend==0.1.6` is installed."
    ) from exc


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


def required_env(name: str) -> str:
    """Return env var value or exit with a clear startup error."""
    value = os.getenv(name)
    if value:
        return value
    raise SystemExit(f"Missing required environment variable: {name}")


def resolve_workspace_root() -> Path:
    """Resolve and create the agent workspace root directory."""
    raw_root = os.getenv("AGENT_WORKSPACE_ROOT", "data/agent-workspace")
    path = Path(raw_root)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_backend() -> LocalBackend:
    """Create the local filesystem backend with shell execution disabled."""
    return LocalBackend(root_dir=resolve_workspace_root(), enable_execute=False)


def validate_console_deps_contract() -> None:
    """Fail fast if console toolset structural assumptions stop holding."""
    try:
        backend_annotation = get_type_hints(AgentDeps).get("backend")
    except (NameError, TypeError) as exc:
        raise SystemExit(
            "Failed to resolve AgentDeps type annotations for console toolset validation."
        ) from exc
    if backend_annotation is not LocalBackend:
        raise SystemExit(
            "AgentDeps.backend must be typed as LocalBackend to satisfy "
            "console toolset dependency expectations."
        )

    required_backend_methods = ("ls_info", "read", "write", "edit", "glob_info", "grep_raw")
    missing = [
        name for name in required_backend_methods if not callable(getattr(LocalBackend, name, None))
    ]
    if missing:
        raise SystemExit(
            "LocalBackend is missing required console backend methods: "
            + ", ".join(sorted(missing))
        )


def _resolve_shipped_skills_dir() -> Path:
    raw = os.getenv("SKILLS_DIR", "skills")
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def _resolve_custom_skills_dir() -> Path:
    raw = os.getenv("CUSTOM_SKILLS_DIR", "skills")
    path = Path(raw)
    if not path.is_absolute():
        path = resolve_workspace_root() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_skill_directories() -> list[SkillDirectory]:
    shipped_dir = _resolve_shipped_skills_dir()
    custom_dir = _resolve_custom_skills_dir()
    if shipped_dir.resolve() == custom_dir.resolve():
        return [SkillDirectory(path=shipped_dir)]
    return [SkillDirectory(path=shipped_dir), SkillDirectory(path=custom_dir)]


_READ_ONLY_EXEC_TOOLS: frozenset[str] = frozenset({"process_list", "process_poll", "process_log"})


def _needs_exec_approval(
    ctx: RunContext[AgentDeps],
    tool_def: ToolDefinition,
    tool_args: dict[str, Any],
) -> bool:
    """Require approval for mutating exec tools; skip for read-only ones."""
    return tool_def.name not in _READ_ONLY_EXEC_TOOLS


async def _prepare_exec_tools(
    ctx: RunContext[AgentDeps],
    tool_defs: list[ToolDefinition],
) -> list[ToolDefinition] | None:
    """Hide exec tools when ENABLE_EXECUTE is not set."""
    if os.getenv("ENABLE_EXECUTE", "").lower() not in ("1", "true", "yes"):
        return []
    return tool_defs


def _build_exec_toolset() -> AbstractToolset[AgentDeps]:
    """Build the exec/process toolset with dynamic visibility and approval."""
    from pydantic_ai import FunctionToolset, Tool

    from exec_tool import execute, execute_pty
    from process_tool import (
        process_kill,
        process_list,
        process_log,
        process_poll,
        process_send_keys,
        process_write,
    )

    exec_meta: dict[str, str] = {"category": "exec"}
    proc_meta: dict[str, str] = {"category": "process"}
    ts: FunctionToolset[AgentDeps] = FunctionToolset(
        tools=[
            Tool(execute, metadata=exec_meta),
            Tool(execute_pty, metadata=exec_meta),
            Tool(process_list, metadata=proc_meta),
            Tool(process_poll, metadata=proc_meta),
            Tool(process_log, metadata=proc_meta),
            Tool(process_write, metadata=proc_meta),
            Tool(process_send_keys, metadata=proc_meta),
            Tool(process_kill, metadata=proc_meta),
        ],
        docstring_format="google",
        require_parameter_descriptions=True,
    )

    # Clean up old exec logs at startup
    workspace = resolve_workspace_root()
    from exec_registry import cleanup_exec_logs

    cleanup_exec_logs(workspace)

    return ts.prepared(_prepare_exec_tools).approval_required(_needs_exec_approval)


def build_toolsets(
    memory_db_path: str | None = None,
    subscription_registry: SubscriptionRegistry | None = None,
) -> tuple[list[AbstractToolset[AgentDeps]], str]:
    """Build all toolsets and return their static capability system prompt."""
    validate_console_deps_contract()
    console = create_console_toolset(include_execute=False, require_write_approval=True)
    skills_toolset, skills_instr = create_skills_toolset(_build_skill_directories())
    toolsets: list[AbstractToolset[AgentDeps]] = [console, skills_toolset]
    system_prompt_fragments: list[str] = [
        BASE_SYSTEM_PROMPT,
        CONSOLE_INSTRUCTIONS,
        skills_instr,
    ]

    exec_enabled = os.getenv("ENABLE_EXECUTE", "").lower() in ("1", "true", "yes")
    toolsets.append(_build_exec_toolset())
    if exec_enabled:
        system_prompt_fragments.append(EXEC_INSTRUCTIONS)

    if memory_db_path is not None:
        workspace_root = resolve_workspace_root()
        memory_toolset, memory_instr = create_memory_toolset(memory_db_path, workspace_root)
        toolsets.append(memory_toolset)
        system_prompt_fragments.append(memory_instr)

    if subscription_registry is not None:
        sub_toolset, sub_instr = create_subscription_toolset(subscription_registry)
        toolsets.append(sub_toolset)
        system_prompt_fragments.append(sub_instr)

    return wrap_toolsets(toolsets), compose_system_prompt(system_prompt_fragments)


async def _strict_tool_definitions(
    ctx: RunContext[AgentDeps],
    tool_defs: list[ToolDefinition],
) -> list[ToolDefinition] | None:
    """Enable strict JSON schema validation on every tool definition.

    OpenRouter and OpenAI-compatible providers produce fewer malformed
    tool-call arguments when tool schemas are marked ``strict=True``.

    This is OpenRouter-only because Anthropic's native API does not support
    the ``strict`` field on tool definitions — it is an OpenAI-compatible
    extension.  The callback must be async (returning ``Awaitable``) to
    satisfy PydanticAI's ``ToolsPrepareFunc`` type signature, even though
    the body performs no I/O.
    """
    return [replace(td, strict=True) for td in tool_defs]


def build_model_settings() -> ModelSettings | None:
    """Build ModelSettings from AI_TEMPERATURE, AI_MAX_TOKENS, AI_TOP_P env vars."""
    settings: ModelSettings = {}
    temp_raw = os.getenv("AI_TEMPERATURE")
    if temp_raw is not None:
        settings["temperature"] = float(temp_raw)
    max_tokens_raw = os.getenv("AI_MAX_TOKENS")
    if max_tokens_raw is not None:
        settings["max_tokens"] = int(max_tokens_raw)
    top_p_raw = os.getenv("AI_TOP_P")
    if top_p_raw is not None:
        settings["top_p"] = float(top_p_raw)
    return settings if settings else None


@dataclass
class AgentOptions:
    """Optional behavioural knobs for :func:`build_agent`."""

    instructions: list[str] | None = None
    history_processors: Sequence[HistoryProcessor[AgentDeps]] = ()
    model_settings: ModelSettings | None = None


def _build_anthropic_model() -> str:
    """Build Anthropic model string. Requires ANTHROPIC_API_KEY."""
    required_env("ANTHROPIC_API_KEY")
    return os.getenv("ANTHROPIC_MODEL", "anthropic:claude-3-5-sonnet-latest")


def _build_openrouter_model() -> OpenAIChatModel:
    """Build OpenRouter model instance. Requires OPENROUTER_API_KEY."""
    return OpenAIChatModel(
        os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        provider=OpenAIProvider(
            base_url="https://openrouter.ai/api/v1",
            api_key=required_env("OPENROUTER_API_KEY"),
        ),
    )


def resolve_model(provider: str) -> Model | str:
    """Resolve primary model with optional fallback for provider resilience.

    When both ANTHROPIC_API_KEY and OPENROUTER_API_KEY are set, wraps the
    primary model (selected by AI_PROVIDER) and the alternate in a
    FallbackModel so requests automatically retry on the other provider.
    """
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    has_openrouter = bool(os.getenv("OPENROUTER_API_KEY"))

    if provider == "anthropic":
        primary: Model | str = _build_anthropic_model()
        if has_openrouter:
            return FallbackModel(primary, _build_openrouter_model())
        return primary

    if provider == "openrouter":
        primary = _build_openrouter_model()
        if has_anthropic:
            return FallbackModel(primary, _build_anthropic_model())
        return primary

    raise SystemExit("Unsupported AI_PROVIDER. Use 'openrouter' or 'anthropic'.")


def build_agent(
    provider: str,
    agent_name: str,
    toolsets: list[AbstractToolset[AgentDeps]],
    system_prompt: str,
    options: AgentOptions | None = None,
) -> Agent[AgentDeps, str]:
    """Create the configured agent from explicit provider/name/toolset settings."""
    opts = options or AgentOptions()
    hp = list(opts.history_processors)
    dynamic_instructions = opts.instructions if opts.instructions is not None else None
    effective_settings = opts.model_settings or build_model_settings()
    model = resolve_model(provider)
    return Agent(
        model,
        deps_type=AgentDeps,
        toolsets=toolsets,
        system_prompt=system_prompt,
        instructions=dynamic_instructions,
        history_processors=hp,
        name=agent_name,
        prepare_tools=_strict_tool_definitions,
        model_settings=effective_settings,
        end_strategy="exhaustive",
    )


def instrument_agent(agent: Agent[AgentDeps, str]) -> bool:
    """Enable OpenTelemetry instrumentation on the agent if configured.

    Activates ``Agent.instrument_all()`` when the ``OTEL_EXPORTER_OTLP_ENDPOINT``
    environment variable is set, allowing trace export to any OTLP-compatible
    collector.  Returns ``True`` when instrumentation was applied.

    Uses the class-level ``instrument_all`` so all agents (including any
    created later) inherit the setting.  The *agent* parameter is accepted
    for call-site clarity but is not strictly required.
    """
    _ = agent  # kept for call-site readability
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    Agent.instrument_all()
    return True
