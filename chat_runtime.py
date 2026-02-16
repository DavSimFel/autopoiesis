"""Runtime initialization helpers for CLI chat."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_type_hints

from pydantic_ai import AbstractToolset, Agent
from pydantic_ai._agent_graph import HistoryProcessor
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from approval_keys import ApprovalKeyManager
from approval_policy import ToolPolicyRegistry
from approval_store import ApprovalStore
from models import AgentDeps
from skills import SkillDirectory, create_skills_toolset

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


_CONSOLE_INSTRUCTIONS = (
    "You have filesystem tools for reading, writing, and editing files "
    "in the workspace. Write and edit operations require user approval. "
    "Shell execution is disabled."
)


def build_toolsets() -> tuple[list[AbstractToolset[AgentDeps]], list[str]]:
    """Build all toolsets and collect their system prompt instructions."""
    validate_console_deps_contract()
    console = create_console_toolset(include_execute=False, require_write_approval=True)
    skills_toolset, skills_instr = create_skills_toolset(_build_skill_directories())
    toolsets: list[AbstractToolset[AgentDeps]] = [console, skills_toolset]
    instructions = [i for i in [_CONSOLE_INSTRUCTIONS, skills_instr] if i]
    return toolsets, instructions


def build_agent(
    provider: str,
    agent_name: str,
    toolsets: list[AbstractToolset[AgentDeps]],
    instructions: list[str],
    history_processors: Sequence[HistoryProcessor[AgentDeps]] | None = None,
) -> Agent[AgentDeps, str]:
    """Create the configured agent from explicit provider/name/toolset/instructions."""
    all_instructions: list[str] = [
        "You are a helpful coding assistant with filesystem and skill tools.",
        *instructions,
    ]
    hp = history_processors or []
    if provider == "anthropic":
        required_env("ANTHROPIC_API_KEY")
        return Agent(
            os.getenv("ANTHROPIC_MODEL", "anthropic:claude-3-5-sonnet-latest"),
            deps_type=AgentDeps,
            toolsets=toolsets,
            instructions=all_instructions,
            history_processors=hp,
            name=agent_name,
        )
    if provider == "openrouter":
        model = OpenAIChatModel(
            os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
            provider=OpenAIProvider(
                base_url="https://openrouter.ai/api/v1",
                api_key=required_env("OPENROUTER_API_KEY"),
            ),
        )
        return Agent(
            model,
            deps_type=AgentDeps,
            toolsets=toolsets,
            instructions=all_instructions,
            history_processors=hp,
            name=agent_name,
        )
    raise SystemExit("Unsupported AI_PROVIDER. Use 'openrouter' or 'anthropic'.")
