"""Toolset, backend, and workspace wiring for chat runtime."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any, get_type_hints

from pydantic_ai import AbstractToolset, RunContext
from pydantic_ai.tools import ToolDefinition

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
    missing_package = exc.name or "unknown package"
    raise SystemExit(
        f"Missing backend dependency package `{missing_package}`. "
        "Run `uv sync` so `pydantic-ai-backend==0.1.6` is installed."
    ) from exc


_READ_ONLY_EXEC_TOOLS: frozenset[str] = frozenset({"process_list", "process_poll", "process_log"})


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

    required_methods = ("ls_info", "read", "write", "edit", "glob_info", "grep_raw")
    missing = [name for name in required_methods if not callable(getattr(LocalBackend, name, None))]
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


def _needs_exec_approval(
    _: RunContext[AgentDeps],
    tool_def: ToolDefinition,
    _tool_args: dict[str, Any],
) -> bool:
    """Require approval for mutating exec tools; skip for read-only ones."""
    return tool_def.name not in _READ_ONLY_EXEC_TOOLS


async def _prepare_exec_tools(
    _: RunContext[AgentDeps],
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
    toolset = FunctionToolset[AgentDeps](
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

    # Startup cleanup avoids stale logs from prior runs polluting process views.
    from exec_registry import cleanup_exec_logs

    cleanup_exec_logs(resolve_workspace_root())
    return toolset.prepared(_prepare_exec_tools).approval_required(_needs_exec_approval)


def build_toolsets(
    memory_db_path: str | None = None,
    subscription_registry: SubscriptionRegistry | None = None,
) -> tuple[list[AbstractToolset[AgentDeps]], str]:
    """Build all toolsets and return their static capability system prompt."""
    validate_console_deps_contract()
    console = create_console_toolset(include_execute=False, require_write_approval=True)
    skills_toolset, skills_instr = create_skills_toolset(_build_skill_directories())

    toolsets: list[AbstractToolset[AgentDeps]] = [console, skills_toolset, _build_exec_toolset()]
    prompt_fragments: list[str] = [BASE_SYSTEM_PROMPT, CONSOLE_INSTRUCTIONS, skills_instr]

    exec_enabled = os.getenv("ENABLE_EXECUTE", "").lower() in ("1", "true", "yes")
    if exec_enabled:
        prompt_fragments.append(EXEC_INSTRUCTIONS)

    if memory_db_path is not None:
        memory_toolset, memory_instr = create_memory_toolset(
            memory_db_path, resolve_workspace_root()
        )
        toolsets.append(memory_toolset)
        prompt_fragments.append(memory_instr)

    if subscription_registry is not None:
        sub_toolset, sub_instr = create_subscription_toolset(subscription_registry)
        toolsets.append(sub_toolset)
        prompt_fragments.append(sub_instr)

    return wrap_toolsets(toolsets), compose_system_prompt(prompt_fragments)


async def strict_tool_definitions(
    _: RunContext[AgentDeps],
    tool_defs: list[ToolDefinition],
) -> list[ToolDefinition] | None:
    """Mark all tool definitions strict for OpenAI-compatible provider schemas."""
    return [replace(tool_def, strict=True) for tool_def in tool_defs]
