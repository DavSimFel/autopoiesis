"""Toolset, backend, and workspace wiring for chat runtime."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any, get_type_hints

from pydantic_ai import AbstractToolset, RunContext
from pydantic_ai.tools import ToolDefinition

from autopoiesis.models import AgentDeps
from autopoiesis.prompts import (
    BASE_SYSTEM_PROMPT,
    CONSOLE_INSTRUCTIONS,
    EXEC_INSTRUCTIONS,
    compose_system_prompt,
)
from autopoiesis.skills.skills import SkillDirectory, create_skills_toolset
from autopoiesis.store.knowledge import (
    ensure_journal_entry,
    init_knowledge_index,
    load_knowledge_context,
    reindex_knowledge,
)
from autopoiesis.store.subscriptions import SubscriptionRegistry
from autopoiesis.tools.categories import resolve_enabled_categories
from autopoiesis.tools.knowledge_tools import create_knowledge_toolset
from autopoiesis.tools.subscription_tools import create_subscription_toolset
from autopoiesis.tools.toolset_wrappers import wrap_toolsets
from autopoiesis.tools.topic_tools import create_topic_toolset
from autopoiesis.topics.topic_manager import TopicRegistry

try:
    from pydantic_ai_backends import LocalBackend, create_console_toolset
except ModuleNotFoundError as exc:
    missing_package = exc.name or "unknown package"
    raise SystemExit(
        f"Missing backend dependency package `{missing_package}`. "
        "Run `uv sync` so `pydantic-ai-backend==0.1.6` is installed."
    ) from exc

#: Maximum number of tool definitions that may be marked ``strict=True``.
#: Anthropic's API rejects requests with more than 20 strict tools.
_MAX_STRICT_TOOLS = 20

_READ_ONLY_EXEC_TOOLS: frozenset[str] = frozenset({"process_list", "process_poll", "process_log"})


def _repo_root() -> Path:
    """Return the repository root from the src/autopoiesis/tools package path."""
    return Path(__file__).resolve().parents[3]


def resolve_workspace_root() -> Path:
    """Resolve and create the agent workspace root directory."""
    raw_root = os.getenv("AGENT_WORKSPACE_ROOT", "data/agent-workspace")
    path = Path(raw_root)
    if not path.is_absolute():
        path = _repo_root() / path
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
        path = _repo_root() / path
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


def _build_exec_toolset(workspace_root: Path | None = None) -> AbstractToolset[AgentDeps]:
    """Build the exec/process toolset with dynamic visibility and approval.

    *workspace_root* specifies the directory used for exec-log cleanup.  When
    ``None`` the global :func:`resolve_workspace_root` value is used so that
    existing call-sites remain backward-compatible.
    """
    from pydantic_ai import FunctionToolset, Tool

    from autopoiesis.tools.exec_tool import execute, execute_pty
    from autopoiesis.tools.process_tool import (
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
    from autopoiesis.infra.exec_registry import cleanup_exec_logs

    cleanup_exec_logs(workspace_root or resolve_workspace_root())
    return toolset.prepared(_prepare_exec_tools).approval_required(_needs_exec_approval)


def build_toolsets(
    subscription_registry: SubscriptionRegistry | None = None,
    knowledge_db_path: str | None = None,
    knowledge_context: str = "",
    topic_registry: TopicRegistry | None = None,
    tool_names: list[str] | None = None,
    *,
    workspace_root: Path | None = None,
) -> tuple[list[AbstractToolset[AgentDeps]], str]:
    """Build toolsets and return their static capability system prompt.

    *tool_names* is an optional whitelist of tool category names as declared in
    ``AgentConfig.tools`` (e.g. ``["shell", "search", "topics"]``).  When
    ``None`` (default) every toolset is included for backward compatibility.
    When provided, only toolsets whose canonical category appears in the list
    are included; unknown aliases are silently ignored.

    The *console* and *skills* toolsets are always included — they represent
    core read/write and skill-invocation capabilities that every agent needs.

    *workspace_root* is forwarded to :func:`_build_exec_toolset` for per-agent
    exec-log isolation.  When ``None`` the global workspace root is used.
    """
    enabled = resolve_enabled_categories(tool_names)

    def _enabled(category: str) -> bool:
        """Return True when *category* should be included."""
        return enabled is None or category in enabled

    validate_console_deps_contract()
    console = create_console_toolset(include_execute=False, require_write_approval=True)
    skills_toolset, skills_instr = create_skills_toolset(_build_skill_directories())

    # Console and skills are always present (they are core primitives).
    toolsets: list[AbstractToolset[AgentDeps]] = [console, skills_toolset]
    prompt_fragments: list[str] = [BASE_SYSTEM_PROMPT, CONSOLE_INSTRUCTIONS, skills_instr]

    if _enabled("exec"):
        toolsets.append(_build_exec_toolset(workspace_root=workspace_root))
        exec_enabled = os.getenv("ENABLE_EXECUTE", "").lower() in ("1", "true", "yes")
        if exec_enabled:
            prompt_fragments.append(EXEC_INSTRUCTIONS)

    if knowledge_db_path is not None and _enabled("knowledge"):
        knowledge_toolset, knowledge_instr = create_knowledge_toolset(knowledge_db_path)
        toolsets.append(knowledge_toolset)
        prompt_fragments.append(knowledge_instr)
        if knowledge_context:
            prompt_fragments.append(knowledge_context)

    if subscription_registry is not None and _enabled("subscriptions"):
        sub_toolset, sub_instr = create_subscription_toolset(subscription_registry)
        toolsets.append(sub_toolset)
        prompt_fragments.append(sub_instr)

    if topic_registry is not None and _enabled("topics"):
        topic_toolset, topic_instr = create_topic_toolset(topic_registry)
        toolsets.append(topic_toolset)
        prompt_fragments.append(topic_instr)

    return wrap_toolsets(toolsets), compose_system_prompt(prompt_fragments)


def prepare_toolset_context(
    history_db_path: str,
    tool_names: list[str] | None = None,
) -> tuple[
    Path,
    str,
    SubscriptionRegistry,
    TopicRegistry,
    list[AbstractToolset[AgentDeps]],
    str,
]:
    """Initialize runtime stores needed for toolset construction.

    *tool_names* is forwarded to :func:`build_toolsets` to filter which toolsets
    are included.  Pass ``None`` (default) to include all toolsets.
    """
    workspace_root = resolve_workspace_root()
    sub_db_path = str(Path(history_db_path).with_name("subscriptions.sqlite"))
    subscription_registry = SubscriptionRegistry(sub_db_path)
    knowledge_root = workspace_root / "knowledge"
    knowledge_db_path = str(Path(history_db_path).with_name("knowledge.sqlite"))
    init_knowledge_index(knowledge_db_path)
    reindex_knowledge(knowledge_db_path, knowledge_root)
    ensure_journal_entry(knowledge_root)
    knowledge_context = load_knowledge_context(knowledge_root)
    topic_registry = TopicRegistry(workspace_root / "topics")
    toolsets, system_prompt = build_toolsets(
        subscription_registry=subscription_registry,
        knowledge_db_path=knowledge_db_path,
        knowledge_context=knowledge_context,
        topic_registry=topic_registry,
        tool_names=tool_names,
        workspace_root=workspace_root,
    )
    return (
        workspace_root,
        knowledge_db_path,
        subscription_registry,
        topic_registry,
        toolsets,
        system_prompt,
    )


async def strict_tool_definitions(
    _: RunContext[AgentDeps],
    tool_defs: list[ToolDefinition],
) -> list[ToolDefinition] | None:
    """Mark all tool definitions strict for OpenAI-compatible provider schemas."""
    # Anthropic caps strict tools at _MAX_STRICT_TOOLS.
    return [
        replace(tool_def, strict=True) if i < _MAX_STRICT_TOOLS else tool_def
        for i, tool_def in enumerate(tool_defs)
    ]
