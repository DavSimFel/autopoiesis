"""Agent-aware toolset construction (Issue #202).

Functions for building per-agent isolated backends and toolset contexts,
extracted from :mod:`autopoiesis.tools.toolset_builder` to keep that module
within the 300-line architectural limit.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import AbstractToolset

try:
    from pydantic_ai_backends import LocalBackend
except ModuleNotFoundError as exc:
    missing_package = exc.name or "unknown package"
    raise SystemExit(
        f"Missing backend dependency package `{missing_package}`. "
        "Run `uv sync` so `pydantic-ai-backend==0.1.6` is installed."
    ) from exc

from autopoiesis.models import AgentDeps
from autopoiesis.store.knowledge import (
    ensure_journal_entry,
    init_knowledge_index,
    load_knowledge_context,
    reindex_knowledge,
)
from autopoiesis.store.subscriptions import SubscriptionRegistry
from autopoiesis.topics.topic_manager import TopicRegistry


def build_backend_for_agent(agent_workspace: Path) -> LocalBackend:
    """Create a :class:`LocalBackend` rooted at the agent's workspace directory.

    Unlike :func:`~autopoiesis.tools.toolset_builder.build_backend` (which reads
    the global ``AGENT_WORKSPACE_ROOT`` env var), this function uses the
    *agent_workspace* path resolved by
    :func:`~autopoiesis.agent.workspace.resolve_agent_workspace` so that each
    agent's file-system toolset is isolated to its own subtree.
    """
    agent_workspace.mkdir(parents=True, exist_ok=True)
    return LocalBackend(root_dir=agent_workspace, enable_execute=False)


def prepare_toolset_context_for_agent(
    agent_id: str,
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
    """Agent-aware variant of :func:`~autopoiesis.tools.toolset_builder.prepare_toolset_context`.

    Unlike the global variant, every path (workspace root, knowledge index,
    subscription database, topics directory) is derived from the agent's
    isolated directory tree returned by
    :func:`~autopoiesis.agent.workspace.resolve_agent_workspace`.  This
    guarantees that toolset state for *agent_id* never leaks into another
    agent's stores.

    *history_db_path* is still accepted as a parameter because the DBOS
    history database is typically shared across agents at the system level;
    callers may pass an agent-specific path if desired.

    Returns the same six-tuple as
    :func:`~autopoiesis.tools.toolset_builder.prepare_toolset_context`:
    ``(workspace_root, knowledge_db_path, subscription_registry,
    topic_registry, toolsets, system_prompt)``.
    """
    # Deferred import avoids circular dependency: workspace → toolset_builder.
    from autopoiesis.agent.workspace import resolve_agent_workspace
    from autopoiesis.tools.toolset_builder import build_toolsets

    agent_paths = resolve_agent_workspace(agent_id)

    workspace_root = agent_paths.workspace
    workspace_root.mkdir(parents=True, exist_ok=True)

    data_dir = agent_paths.data
    data_dir.mkdir(parents=True, exist_ok=True)

    # Each agent gets its own knowledge and subscription DBs.
    knowledge_root = agent_paths.knowledge
    knowledge_root.mkdir(parents=True, exist_ok=True)
    knowledge_db_path = str(data_dir / "knowledge.sqlite")
    sub_db_path = str(data_dir / "subscriptions.sqlite")

    subscription_registry = SubscriptionRegistry(sub_db_path)

    init_knowledge_index(knowledge_db_path)
    reindex_knowledge(knowledge_db_path, knowledge_root)
    ensure_journal_entry(knowledge_root)
    knowledge_context = load_knowledge_context(knowledge_root)

    topics_dir = workspace_root / "topics"
    topic_registry = TopicRegistry(topics_dir)

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
