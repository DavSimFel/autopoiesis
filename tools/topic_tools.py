"""PydanticAI tool definitions for topic management.

Exposes activate_topic, deactivate_topic, and list_topics as agent tools
backed by the TopicRegistry.
"""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from models import AgentDeps
from topic_manager import TopicRegistry

_TOPIC_INSTRUCTIONS = """\
## Topics
Topics are situational context bundles that inject task-specific instructions
and subscriptions when activated.
- `activate_topic` — activate a topic for the current session
- `deactivate_topic` — deactivate a topic
- `list_topics` — show all available topics with status"""


def _register_tools(
    toolset: FunctionToolset[AgentDeps],
    registry: TopicRegistry,
) -> None:
    """Register all topic tools on the toolset."""
    topic_meta: dict[str, str] = {"category": "topics"}

    @toolset.tool(metadata=topic_meta)
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
        registry.activate(name)
        return f"Activated topic '{name}'. Its instructions are now in context."

    @toolset.tool(metadata=topic_meta)
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

    @toolset.tool(metadata=topic_meta)
    async def list_topics(
        ctx: RunContext[AgentDeps],
    ) -> str:
        """List all available topics with their triggers and activation status."""
        topics = registry.list_topics()
        if not topics:
            return "No topics found."
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

    # Ensure closures are retained
    _ = (activate_topic, deactivate_topic, list_topics)


def create_topic_toolset(
    registry: TopicRegistry,
) -> tuple[FunctionToolset[AgentDeps], str]:
    """Create topic tools and return toolset with instructions."""
    toolset: FunctionToolset[AgentDeps] = FunctionToolset(
        docstring_format="google",
        require_parameter_descriptions=True,
    )
    _register_tools(toolset, registry)
    return toolset, _TOPIC_INSTRUCTIONS
