"""History processor pipeline construction.

Dependencies: agent.context, agent.truncation, agent.worker,
    infra.subscription_processor, infra.topic_processor,
    store.subscriptions, toolset_builder, topic_manager
Wired in: chat.py → _initialize_runtime()
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic_ai.messages import ModelMessage

from autopoiesis.agent.context import compact_history
from autopoiesis.agent.truncation import truncate_tool_results
from autopoiesis.agent.worker import checkpoint_history_processor
from autopoiesis.infra.subscription_processor import materialize_subscriptions
from autopoiesis.infra.topic_processor import inject_topic_context
from autopoiesis.store.subscriptions import SubscriptionRegistry
from autopoiesis.tools.toolset_builder import resolve_workspace_root
from autopoiesis.topics.topic_manager import TopicRegistry


def _truncate_processor(msgs: list[ModelMessage]) -> list[ModelMessage]:
    """Truncate oversized tool results in message history."""
    return truncate_tool_results(msgs, resolve_workspace_root())


def _compact_processor(msgs: list[ModelMessage]) -> list[ModelMessage]:
    """Compact older messages when token usage exceeds threshold."""
    return compact_history(msgs)


def build_history_processors(
    *,
    subscription_registry: SubscriptionRegistry,
    workspace_root: Path,
    knowledge_db_path: str,
    topic_registry: TopicRegistry,
) -> list[Callable[[list[ModelMessage]], list[ModelMessage]]]:
    """Build ordered message history processors for agent runs."""

    def _subscription_processor(msgs: list[ModelMessage]) -> list[ModelMessage]:
        return materialize_subscriptions(
            msgs,
            subscription_registry,
            workspace_root,
            knowledge_db_path,
        )

    def _topic_processor(msgs: list[ModelMessage]) -> list[ModelMessage]:
        return inject_topic_context(msgs, topic_registry)

    return [
        _truncate_processor,
        _compact_processor,
        _subscription_processor,
        _topic_processor,
        checkpoint_history_processor,
    ]
