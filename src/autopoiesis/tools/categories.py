"""Canonical tool category constants and alias resolution for AgentConfig.tools."""

from __future__ import annotations

#: Canonical category name for each toolset understood by the runtime.
#: These match what ``AgentConfig.tools`` entries refer to.
CANONICAL_CATEGORIES: frozenset[str] = frozenset(
    {"console", "exec", "skills", "knowledge", "subscriptions", "topics"}
)

#: Alias map from AgentConfig tool name → canonical category.
TOOL_CATEGORY_ALIASES: dict[str, str] = {
    # Filesystem / console toolset
    "shell": "console",
    "console": "console",
    "files": "console",
    # Shell execution toolset
    "exec": "exec",
    "execute": "exec",
    # Skills toolset
    "skills": "skills",
    "skill": "skills",
    # Knowledge / search toolset
    "search": "knowledge",
    "knowledge": "knowledge",
    # Subscription toolset
    "subscriptions": "subscriptions",
    "subscription": "subscriptions",
    # Topic toolset
    "topics": "topics",
    "topic": "topics",
}


def resolve_enabled_categories(
    tool_names: list[str] | None,
) -> frozenset[str] | None:
    """Convert an ``AgentConfig.tools`` list to a canonical category frozenset.

    Returns ``None`` when *tool_names* is ``None``, meaning all categories are
    enabled (backward-compatible default).  Returns an empty frozenset when
    *tool_names* is an empty list (agent uses no optional toolsets).

    Unknown aliases are passed through so that forward-compatibility is
    maintained — unrecognised names are silently ignored by callers that
    iterate over known categories.
    """
    if tool_names is None:
        return None
    return frozenset(
        TOOL_CATEGORY_ALIASES.get(name.strip().lower(), name.strip().lower()) for name in tool_names
    )
