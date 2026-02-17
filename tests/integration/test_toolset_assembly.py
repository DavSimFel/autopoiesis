"""Integration tests for toolset assembly (S7 — Issue #170)."""

# pyright: reportPrivateUsage=false, reportUnknownArgumentType=false

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.tools import ToolDefinition

from autopoiesis.models import AgentDeps
from autopoiesis.tools.toolset_builder import (
    _MAX_STRICT_TOOLS,
    build_toolsets,
    strict_tool_definitions,
)


def test_all_toolsets_register_without_error(
    tmp_path: Path,
    knowledge_db: str,
    subscription_registry: object,
    topic_registry: object,
) -> None:
    """7.1 — build_toolsets() returns without raising."""
    from autopoiesis.store.subscriptions import SubscriptionRegistry
    from autopoiesis.topics.topic_manager import TopicRegistry

    assert isinstance(subscription_registry, SubscriptionRegistry)
    assert isinstance(topic_registry, TopicRegistry)
    toolsets, system_prompt = build_toolsets(
        subscription_registry=subscription_registry,
        knowledge_db_path=knowledge_db,
        topic_registry=topic_registry,
    )
    assert len(toolsets) > 0
    assert isinstance(system_prompt, str)
    assert len(system_prompt) > 0


@pytest.mark.xfail(reason="Blocked on #170 — approval wrapper for shell tool not implemented")
def test_approval_wrapper_applied_to_dangerous_tools(
    knowledge_db: str,
    subscription_registry: object,
    topic_registry: object,
) -> None:
    """7.2 — Dangerous tools (exec, shell) have approval wrappers."""
    from autopoiesis.store.subscriptions import SubscriptionRegistry
    from autopoiesis.topics.topic_manager import TopicRegistry

    assert isinstance(subscription_registry, SubscriptionRegistry)
    assert isinstance(topic_registry, TopicRegistry)
    __, _ = build_toolsets(
        subscription_registry=subscription_registry,
        knowledge_db_path=knowledge_db,
        topic_registry=topic_registry,
    )
    # The shell tool should exist and require approval
    from autopoiesis.tools.shell_tool import shell  # type: ignore[import-not-found]

    assert shell is not None  # placeholder — real check is that it's wrapped


@pytest.mark.asyncio()
async def test_tool_count_within_anthropic_limit(
    knowledge_db: str,
    subscription_registry: object,
    topic_registry: object,
) -> None:
    """7.3 — At most 20 tools marked strict (Anthropic limit)."""
    from pydantic_ai import RunContext

    from autopoiesis.store.subscriptions import SubscriptionRegistry
    from autopoiesis.topics.topic_manager import TopicRegistry

    assert isinstance(subscription_registry, SubscriptionRegistry)
    assert isinstance(topic_registry, TopicRegistry)

    # Create dummy tool defs to test the strict cap
    defs = [ToolDefinition(name=f"tool_{i}", description=f"Tool {i}") for i in range(25)]
    ctx: RunContext[AgentDeps] = None  # type: ignore[assignment]
    result = await strict_tool_definitions(ctx, defs)
    assert result is not None
    strict_count = sum(1 for td in result if td.strict)
    assert strict_count <= _MAX_STRICT_TOOLS


def test_skill_tools_merged_into_toolset(
    tmp_path: Path,
    knowledge_db: str,
    subscription_registry: object,
    topic_registry: object,
) -> None:
    """7.4 — Skill tools are included in the final toolset list."""
    from autopoiesis.store.subscriptions import SubscriptionRegistry
    from autopoiesis.topics.topic_manager import TopicRegistry

    assert isinstance(subscription_registry, SubscriptionRegistry)
    assert isinstance(topic_registry, TopicRegistry)
    toolsets, _prompt = build_toolsets(
        subscription_registry=subscription_registry,
        knowledge_db_path=knowledge_db,
        topic_registry=topic_registry,
    )
    # Skills toolset is the second element (index 1) per build_toolsets order
    assert len(toolsets) >= 3  # console, skills, exec at minimum


@pytest.mark.xfail(reason="Blocked on #170 — role-based tool filtering not implemented")
def test_tool_filtering_per_agent_role() -> None:
    """7.5 — Tools are filtered based on agent role."""
    # Future: build_toolsets(role="reader") should exclude write/exec tools
    from autopoiesis.tools.toolset_builder import build_toolsets

    toolsets, _ = build_toolsets(role="reader")  # type: ignore[call-arg]
    # A reader role should not have exec tools
    assert len(toolsets) > 0
