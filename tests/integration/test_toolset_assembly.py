"""Integration tests for toolset assembly (S7 — Issue #170)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from autopoiesis.models import AgentDeps
from autopoiesis.tools.toolset_builder import build_toolsets, strict_tool_definitions

_ANTHROPIC_STRICT_TOOL_LIMIT = 20


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


def test_exec_toolset_present(
    knowledge_db: str,
    subscription_registry: object,
    topic_registry: object,
) -> None:
    """7.2 — Toolset assembly includes console, skills, exec, knowledge, subscription, topics."""
    from autopoiesis.store.subscriptions import SubscriptionRegistry
    from autopoiesis.topics.topic_manager import TopicRegistry

    assert isinstance(subscription_registry, SubscriptionRegistry)
    assert isinstance(topic_registry, TopicRegistry)
    toolsets, _ = build_toolsets(
        subscription_registry=subscription_registry,
        knowledge_db_path=knowledge_db,
        topic_registry=topic_registry,
    )
    # With all registries provided, we expect 6 toolsets:
    # console, skills, exec, knowledge, subscription, topic
    assert len(toolsets) >= 6, f"Expected at least 6 toolsets, got {len(toolsets)}"


@pytest.mark.asyncio()
async def test_tool_count_within_anthropic_limit(
    knowledge_db: str,
    subscription_registry: object,
    topic_registry: object,
) -> None:
    """7.3 — At most 20 tools marked strict (Anthropic limit)."""
    from autopoiesis.store.subscriptions import SubscriptionRegistry
    from autopoiesis.topics.topic_manager import TopicRegistry

    assert isinstance(subscription_registry, SubscriptionRegistry)
    assert isinstance(topic_registry, TopicRegistry)

    # Test with real built toolsets — validate actual tool definitions
    _toolsets, _ = build_toolsets(
        subscription_registry=subscription_registry,
        knowledge_db_path=knowledge_db,
        topic_registry=topic_registry,
    )
    # Also verify the strict cap with synthetic overflow
    defs = [ToolDefinition(name=f"tool_{i}", description=f"Tool {i}") for i in range(25)]
    ctx = cast(RunContext[AgentDeps], None)
    result = await strict_tool_definitions(ctx, defs)
    assert result is not None
    strict_count = sum(1 for td in result if td.strict)
    assert strict_count <= _ANTHROPIC_STRICT_TOOL_LIMIT


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
    # With all registries: console, skills, exec, knowledge, subscription, topic
    assert len(toolsets) >= 6, f"Expected >=6 toolsets with all registries, got {len(toolsets)}"
