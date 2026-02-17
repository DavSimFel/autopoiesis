"""PydanticAI tool definitions for topic management.

Exposes activate_topic, deactivate_topic, list_topics, and lifecycle tools
(create, update status, set owner, query) backed by the TopicRegistry.
"""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from autopoiesis.models import AgentDeps
from autopoiesis.topics.topic_manager import (
    Topic,
    TopicRegistry,
)
from autopoiesis.topics.topic_manager import (
    create_topic as _create_topic,
)
from autopoiesis.topics.topic_manager import (
    query_topics as _query_topics,
)
from autopoiesis.topics.topic_manager import (
    set_topic_owner as _set_topic_owner,
)
from autopoiesis.topics.topic_manager import (
    update_topic_status as _update_topic_status,
)

_TOPIC_INSTRUCTIONS = """\
## Topics
Topics are situational context bundles that inject task-specific instructions
and subscriptions when activated.
- `activate_topic` — activate a topic for the current session
- `deactivate_topic` — deactivate a topic
- `list_topics` — show all available topics with status
- `create_topic` — create a new topic file with type and optional owner
- `update_topic_status` — transition a topic's lifecycle status
- `set_topic_owner` — assign an owner role to a topic
- `query_topics` — filter topics by type, status, or owner"""


def _try_activate(registry: TopicRegistry, name: str) -> str | None:
    """Attempt activation, returning error string or None on success."""
    try:
        registry.activate(name)
    except ValueError as exc:
        return str(exc)
    return None


def _format_topic_list(registry: TopicRegistry, topics: list[Topic]) -> str:
    """Format all topics for display."""
    lines: list[str] = []
    for topic in topics:
        status = "🟢 active" if registry.is_active(topic.name) else "⚪ inactive"
        enabled = "enabled" if topic.enabled else "disabled"
        trigger_types = ", ".join(t.type for t in topic.triggers) or "none"
        lines.append(
            f"- **{topic.name}** [{status}] ({enabled}) "
            f"triggers: {trigger_types} | priority: {topic.priority}"
        )
    return "\n".join(lines)


def _register_core_tools(
    toolset: FunctionToolset[AgentDeps],
    registry: TopicRegistry,
    meta: dict[str, str],
) -> None:
    """Register activate, deactivate, and list tools."""

    @toolset.tool(metadata=meta)
    async def activate_topic(
        ctx: RunContext[AgentDeps],
        name: str,
    ) -> str:
        """Activate a topic to inject its instructions into the current session.

        Args:
            name: Name of the topic to activate (filename without .md extension).
        """
        topic = registry.get_topic(name)
        if topic is None:
            available = ", ".join(t.name for t in registry.list_topics())
            return f"Topic '{name}' not found. Available: {available}"
        if not topic.enabled:
            return f"Topic '{name}' is disabled."
        if registry.is_active(name):
            return f"Topic '{name}' is already active."
        error = _try_activate(registry, name)
        if error is not None:
            return error
        return f"Activated topic '{name}'. Its instructions are now in context."

    @toolset.tool(metadata=meta)
    async def deactivate_topic(
        ctx: RunContext[AgentDeps],
        name: str,
    ) -> str:
        """Deactivate a topic, removing its instructions from context.

        Args:
            name: Name of the topic to deactivate.
        """
        if not registry.is_active(name):
            return f"Topic '{name}' is not active."
        registry.deactivate(name)
        return f"Deactivated topic '{name}'."

    @toolset.tool(metadata=meta)
    async def list_topics(
        ctx: RunContext[AgentDeps],
    ) -> str:
        """List all available topics with their triggers and activation status."""
        topics = registry.list_topics()
        if not topics:
            return "No topics found."
        return _format_topic_list(registry, topics)

    _ = (activate_topic, deactivate_topic, list_topics)


def _register_lifecycle_tools(
    toolset: FunctionToolset[AgentDeps],
    registry: TopicRegistry,
    meta: dict[str, str],
) -> None:
    """Register lifecycle tools: create, update status, set owner, query."""

    @toolset.tool(metadata=meta)
    async def update_topic_status(
        ctx: RunContext[AgentDeps],
        name: str,
        status: str,
    ) -> str:
        """Transition a topic's lifecycle status (e.g. open → in-progress → done).

        Args:
            name: Name of the topic to update.
            status: Target status (open, in-progress, review, done, archived).
        """
        return _update_topic_status(registry, name, status)

    @toolset.tool(metadata=meta)
    async def set_topic_owner(
        ctx: RunContext[AgentDeps],
        name: str,
        owner: str,
    ) -> str:
        """Assign an owner role to a topic for routing.

        Args:
            name: Name of the topic.
            owner: Agent role string to assign as owner.
        """
        return _set_topic_owner(registry, name, owner)

    @toolset.tool(metadata=meta)
    async def create_topic(
        ctx: RunContext[AgentDeps],
        name: str,
        topic_type: str = "general",
        body: str = "",
        owner: str | None = None,
    ) -> str:
        """Create a new topic file with frontmatter and body.

        Args:
            name: Name for the new topic (becomes filename).
            topic_type: Topic type (general, task, project, goal, review, conversation).
            body: Markdown body content for the topic instructions.
            owner: Optional agent role to assign as owner.
        """
        return _create_topic(registry, name, type=topic_type, body=body, owner=owner)

    @toolset.tool(metadata=meta)
    async def query_topics(
        ctx: RunContext[AgentDeps],
        topic_type: str | None = None,
        status: str | None = None,
        owner: str | None = None,
    ) -> str:
        """Filter topics by type, status, and/or owner.

        Args:
            topic_type: Filter by topic type (e.g. task, project).
            status: Filter by lifecycle status (e.g. open, done).
            owner: Filter by owner role.
        """
        results = _query_topics(
            registry,
            type=topic_type,
            status=status,
            owner=owner,
        )
        if not results:
            return "No topics match the given filters."
        return _format_topic_list(registry, results)

    _ = (update_topic_status, set_topic_owner, create_topic, query_topics)


def create_topic_toolset(
    registry: TopicRegistry,
) -> tuple[FunctionToolset[AgentDeps], str]:
    """Create topic tools and return toolset with instructions."""
    toolset: FunctionToolset[AgentDeps] = FunctionToolset(
        docstring_format="google",
        require_parameter_descriptions=True,
    )
    meta: dict[str, str] = {"category": "topics"}
    _register_core_tools(toolset, registry, meta)
    _register_lifecycle_tools(toolset, registry, meta)
    return toolset, _TOPIC_INSTRUCTIONS
