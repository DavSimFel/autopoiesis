"""PydanticAI tool definitions for subscription management.

Exposes subscribe_file, subscribe_knowledge, unsubscribe, unsubscribe_all,
and list_subscriptions as agent tools backed by the SubscriptionRegistry.

Dependencies: models, store.subscriptions
Wired in: toolset_builder.py → build_toolsets()
"""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from models import AgentDeps
from store.subscriptions import SubscriptionKind, SubscriptionRegistry

_LINE_RANGE_PARTS = 2

_SUBSCRIPTION_INSTRUCTIONS = """\
## Context subscriptions
You can subscribe to files or knowledge queries for automatic context injection.
Subscribed content is refreshed and injected before every turn — no need to
re-read manually.
- `subscribe_file` — watch a file (optionally specific lines)
- `subscribe_knowledge` — watch a knowledge search query
- `unsubscribe` / `unsubscribe_all` — stop watching
- `list_subscriptions` — show active subscriptions
Max 10 subscriptions. Each capped at 2000 chars. Auto-expire after 24h."""


def _parse_line_range(lines: str | None) -> tuple[int, int] | None:
    """Parse a 'start-end' line range string."""
    if lines is None:
        return None
    parts = lines.split("-", 1)
    if len(parts) == _LINE_RANGE_PARTS:
        return (int(parts[0]), int(parts[1]))
    return None


def _format_subscription(sub: object) -> str:
    """Format a single subscription for display."""
    from store.subscriptions import Subscription

    assert isinstance(sub, Subscription)
    desc = f"- **{sub.id}** [{sub.kind}] `{sub.target}`"
    if sub.line_range is not None:
        desc += f" (lines {sub.line_range[0]}-{sub.line_range[1]})"
    if sub.pattern is not None:
        desc += f" (pattern: {sub.pattern})"
    return desc


def _register_tools(
    toolset: FunctionToolset[AgentDeps],
    registry: SubscriptionRegistry,
) -> None:
    """Register all subscription tools on the toolset."""
    sub_meta: dict[str, str] = {"category": "subscriptions"}

    @toolset.tool(metadata=sub_meta)
    async def subscribe_file(
        ctx: RunContext[AgentDeps],
        path: str,
        lines: str | None = None,
        pattern: str | None = None,
    ) -> str:
        """Subscribe to a file for automatic context injection each turn.

        Args:
            path: Relative path to the file within the workspace.
            lines: Optional line range as "start-end" (1-indexed). E.g. "1-50".
            pattern: Optional regex pattern to filter matching lines.
        """
        line_range = _parse_line_range(lines)
        kind: SubscriptionKind = "lines" if line_range is not None else "file"
        try:
            sub = registry.add(
                kind=kind,
                target=path,
                line_range=line_range,
                pattern=pattern,
            )
        except ValueError as exc:
            return str(exc)
        return f"Subscribed to {path} (id: {sub.id})"

    @toolset.tool(metadata=sub_meta)
    async def subscribe_knowledge(
        ctx: RunContext[AgentDeps],
        query: str,
    ) -> str:
        """Subscribe to a knowledge search query for automatic injection each turn.

        Results are refreshed before every agent turn.

        Args:
            query: Natural language search query for knowledge.
        """
        try:
            sub = registry.add(kind="knowledge", target=query)
        except ValueError as exc:
            return str(exc)
        return f"Subscribed to knowledge query '{query}' (id: {sub.id})"

    @toolset.tool(metadata=sub_meta)
    async def unsubscribe(
        ctx: RunContext[AgentDeps],
        subscription_id: str,
    ) -> str:
        """Remove a subscription by its id.

        Args:
            subscription_id: The subscription id returned by subscribe_file/subscribe_knowledge.
        """
        removed = registry.remove(subscription_id)
        if removed:
            return f"Unsubscribed {subscription_id}."
        return f"Subscription {subscription_id} not found."

    @toolset.tool(metadata=sub_meta)
    async def unsubscribe_all(
        ctx: RunContext[AgentDeps],
    ) -> str:
        """Remove all active subscriptions for the current session."""
        count = registry.remove_all()
        return f"Removed {count} subscription(s)."

    @toolset.tool(metadata=sub_meta)
    async def list_subscriptions(
        ctx: RunContext[AgentDeps],
    ) -> str:
        """List all active subscriptions with their current state."""
        active = registry.get_active()
        if not active:
            return "No active subscriptions."
        return "\n".join(_format_subscription(s) for s in active)

    _ = (subscribe_file, subscribe_knowledge, unsubscribe, unsubscribe_all, list_subscriptions)


def create_subscription_toolset(
    registry: SubscriptionRegistry,
) -> tuple[FunctionToolset[AgentDeps], str]:
    """Create subscription tools and return toolset with instructions."""
    toolset: FunctionToolset[AgentDeps] = FunctionToolset(
        docstring_format="google",
        require_parameter_descriptions=True,
    )
    _register_tools(toolset, registry)
    return toolset, _SUBSCRIPTION_INSTRUCTIONS
