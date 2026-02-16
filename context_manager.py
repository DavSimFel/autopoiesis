"""Sliding-window context management with token-based compaction."""

from __future__ import annotations

import os

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

CHARS_PER_TOKEN = 4
"""Approximate character-to-token ratio for estimation."""

DEFAULT_CONTEXT_WINDOW_TOKENS = 100_000
"""Default context window size in tokens."""

DEFAULT_COMPACTION_THRESHOLD = 0.7
"""Fraction of context window that triggers compaction."""


def _get_context_window_tokens() -> int:
    """Read max context window size from environment."""
    raw = os.getenv("CONTEXT_WINDOW_TOKENS", "")
    if not raw.strip():
        return DEFAULT_CONTEXT_WINDOW_TOKENS
    try:
        value = int(raw)
    except ValueError:
        msg = f"CONTEXT_WINDOW_TOKENS must be an integer, got {raw!r}"
        raise ValueError(msg) from None
    if value <= 0:
        msg = f"CONTEXT_WINDOW_TOKENS must be positive, got {value}"
        raise ValueError(msg)
    return value


def _get_compaction_threshold() -> float:
    """Read compaction threshold from environment."""
    raw = os.getenv("COMPACTION_THRESHOLD", "")
    if not raw.strip():
        return DEFAULT_COMPACTION_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        msg = f"COMPACTION_THRESHOLD must be a float, got {raw!r}"
        raise ValueError(msg) from None
    if not 0.0 < value < 1.0:
        msg = f"COMPACTION_THRESHOLD must be between 0 and 1 exclusive, got {value}"
        raise ValueError(msg)
    return value


def estimate_tokens(text: str) -> int:
    """Estimate token count from text using character-based heuristic.

    Args:
        text: Input text to estimate.

    Returns:
        Estimated token count (~4 characters per token).
    """
    return max(1, len(text) // CHARS_PER_TOKEN)


def _message_text(msg: ModelMessage) -> str:
    """Extract a text representation of a message for token counting."""
    if isinstance(msg, ModelRequest):
        parts: list[str] = []
        for part in msg.parts:
            if isinstance(part, (UserPromptPart, SystemPromptPart)):
                content = part.content
                if isinstance(content, str):
                    parts.append(content)
        return " ".join(parts)
    parts_text: list[str] = []
    for part in msg.parts:
        if isinstance(part, TextPart):
            parts_text.append(part.content)
    return " ".join(parts_text)


def _estimate_messages_tokens(messages: list[ModelMessage]) -> int:
    """Sum token estimates for a list of messages."""
    return sum(estimate_tokens(_message_text(m)) for m in messages)


def _summarize_older(messages: list[ModelMessage]) -> str:
    """Build a brief summary of compacted messages."""
    summaries: list[str] = []
    for msg in messages:
        text = _message_text(msg)
        if text:
            preview = text[:120].replace("\n", " ")
            role = "user" if isinstance(msg, ModelRequest) else "assistant"
            summaries.append(f"[{role}] {preview}")
    if not summaries:
        return "[Earlier conversation was compacted to save context space.]"
    header = f"[Compacted {len(messages)} earlier messages]\n"
    return header + "\n".join(summaries)


def compact_history(
    messages: list[ModelMessage],
    max_tokens: int | None = None,
    keep_recent: int = 10,
) -> list[ModelMessage]:
    """Compact older history when token usage exceeds the compaction threshold.

    Keeps the last *keep_recent* messages verbatim.  If estimated token
    usage is above ``compaction_threshold * max_tokens``, older messages
    are replaced with a single summary request message.

    Args:
        messages: Full conversation history.
        max_tokens: Context window size (defaults to env / 100 000).
        keep_recent: Number of recent messages to preserve verbatim.

    Returns:
        Possibly compacted list of messages.
    """
    if max_tokens is None:
        max_tokens = _get_context_window_tokens()
    threshold = _get_compaction_threshold()

    total_tokens = _estimate_messages_tokens(messages)
    if total_tokens <= int(max_tokens * threshold):
        return messages

    if len(messages) <= keep_recent:
        return messages

    older = messages[: -keep_recent]
    recent = messages[-keep_recent:]
    summary_text = _summarize_older(older)
    summary_msg = ModelRequest(parts=[UserPromptPart(content=summary_text)])
    return [summary_msg, *recent]
