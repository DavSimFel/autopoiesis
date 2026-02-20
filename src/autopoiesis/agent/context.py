"""Sliding-window context management with token-based compaction.

Dependencies: pydantic_ai.messages
Wired in: agent/history.py → build_history_processors()
"""

from __future__ import annotations

import logging
import os

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    SystemPromptPart,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)

from autopoiesis.agent.context_tokens import (
    CHARS_PER_TOKEN,
    CHARS_PER_TOKEN_CODE,
    estimate_tokens,
    estimate_tokens_for_model,
)

__all__ = [
    "CHARS_PER_TOKEN",
    "CHARS_PER_TOKEN_CODE",
    "estimate_tokens",
    "estimate_tokens_for_model",
    "check_context_usage",
    "compact_history",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Threshold constants
# ---------------------------------------------------------------------------

DEFAULT_CONTEXT_WINDOW_TOKENS = 100_000
"""Default context window size in tokens."""

DEFAULT_WARNING_THRESHOLD = 0.80
"""Fraction of context window that triggers a proactive warning log."""

DEFAULT_COMPACTION_THRESHOLD = 0.90
"""Fraction of context window that triggers automatic compaction.

Set higher than :data:`DEFAULT_WARNING_THRESHOLD` so a warning always
precedes compaction.  Must be strictly less than 1.0 so compaction fires
*before* the window overflows.
"""

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


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
    """Read compaction threshold from environment.

    The environment variable ``COMPACTION_THRESHOLD`` overrides the default.
    Must be a float strictly between 0 and 1.  Values at or above
    :data:`DEFAULT_WARNING_THRESHOLD` (0.8) guarantee compaction fires before
    overflow.
    """
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


def _get_warning_threshold() -> float:
    """Read warning threshold from environment.

    The environment variable ``CONTEXT_WARNING_THRESHOLD`` overrides the
    default of :data:`DEFAULT_WARNING_THRESHOLD` (0.80).
    """
    raw = os.getenv("CONTEXT_WARNING_THRESHOLD", "")
    if not raw.strip():
        return DEFAULT_WARNING_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        msg = f"CONTEXT_WARNING_THRESHOLD must be a float, got {raw!r}"
        raise ValueError(msg) from None
    if not 0.0 < value < 1.0:
        msg = f"CONTEXT_WARNING_THRESHOLD must be between 0 and 1 exclusive, got {value}"
        raise ValueError(msg)
    return value


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------


def _message_text(msg: ModelMessage) -> str:
    """Extract a text representation of a message for token counting."""
    if isinstance(msg, ModelRequest):
        parts: list[str] = []
        for part in msg.parts:
            if isinstance(part, (UserPromptPart, SystemPromptPart, ToolReturnPart)):
                content = part.content
                if isinstance(content, str):
                    parts.append(content)
        return " ".join(parts)
    parts_text: list[str] = []
    for part in msg.parts:
        if isinstance(part, TextPart):
            parts_text.append(part.content)
    return " ".join(parts_text)


def _estimate_messages_tokens(messages: list[ModelMessage], model_name: str = "") -> int:
    """Sum token estimates for a list of messages."""
    return sum(estimate_tokens(_message_text(m), model_name) for m in messages)


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


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def check_context_usage(
    messages: list[ModelMessage],
    max_tokens: int | None = None,
    model_name: str = "",
) -> float:
    """Return the fraction of the context window consumed by *messages*.

    Emits a WARNING log when usage exceeds :data:`DEFAULT_WARNING_THRESHOLD`
    (80%).

    Args:
        messages: Current conversation history.
        max_tokens: Context window size in tokens (defaults to env /
            :data:`DEFAULT_CONTEXT_WINDOW_TOKENS`).
        model_name: Optional model name for tiktoken estimation.

    Returns:
        A float in ``[0, ∞)`` representing the fill fraction (> 1.0 means
        the window is already over-full).
    """
    if max_tokens is None:
        max_tokens = _get_context_window_tokens()

    total_tokens = _estimate_messages_tokens(messages, model_name)
    fraction = total_tokens / max_tokens
    warning_threshold = _get_warning_threshold()

    if fraction >= warning_threshold:
        pct = fraction * 100
        _log.warning(
            "Context window is %.1f%% full (%d / %d estimated tokens). "
            "Compaction may be triggered soon.",
            pct,
            total_tokens,
            max_tokens,
        )
    return fraction


def compact_history(
    messages: list[ModelMessage],
    max_tokens: int | None = None,
    keep_recent: int = 10,
    model_name: str = "",
) -> list[ModelMessage]:
    """Compact older history when token usage approaches the context limit.

    The function checks token usage **before** the model processes the next
    message, ensuring compaction fires *before* overflow rather than after.

    Compaction replaces older messages with a single summary when estimated
    usage exceeds ``compaction_threshold * max_tokens``.  A proactive WARNING
    is logged whenever usage exceeds ``warning_threshold * max_tokens``
    (default 80%).

    Args:
        messages: Full conversation history.
        max_tokens: Context window size (defaults to env /
            :data:`DEFAULT_CONTEXT_WINDOW_TOKENS`).
        keep_recent: Number of recent messages to preserve verbatim.
        model_name: Optional model name used for tiktoken-based estimation.

    Returns:
        Possibly compacted list of messages.
    """
    if max_tokens is None:
        max_tokens = _get_context_window_tokens()
    compaction_threshold = _get_compaction_threshold()

    total_tokens = _estimate_messages_tokens(messages, model_name)
    fraction = total_tokens / max_tokens

    # Proactive warning when approaching the limit.
    warning_threshold = _get_warning_threshold()
    if fraction >= warning_threshold:
        pct = fraction * 100
        _log.warning(
            "Context window is %.1f%% full (%d / %d estimated tokens).",
            pct,
            total_tokens,
            max_tokens,
        )

    # Compaction fires before the window overflows (< 1.0 threshold).
    if fraction <= compaction_threshold:
        return messages

    if len(messages) <= keep_recent:
        return messages

    older = messages[:-keep_recent]
    recent = messages[-keep_recent:]
    summary_text = _summarize_older(older)
    _log.info(
        "Compacting %d older messages (context at %.1f%% of %d tokens).",
        len(older),
        fraction * 100,
        max_tokens,
    )
    summary_msg = ModelRequest(parts=[UserPromptPart(content=summary_text)])
    return [summary_msg, *recent]
