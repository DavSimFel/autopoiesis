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

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Character-to-token ratios
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN = 4
"""Default character-to-token ratio (natural language, ~4 chars/token)."""

CHARS_PER_TOKEN_CODE = 3.5
"""Character-to-token ratio for code-heavy content (~3.5 chars/token)."""

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
# Tiktoken integration (optional — falls back to char-based estimation)
# ---------------------------------------------------------------------------


def _get_tiktoken_encoder(model_name: str) -> object | None:
    """Return a tiktoken encoder for *model_name*, or ``None`` if unavailable.

    Tries ``tiktoken.encoding_for_model`` first (exact match), then falls back
    to ``tiktoken.get_encoding("cl100k_base")`` for any OpenAI-compatible model
    name.  Returns ``None`` if tiktoken is not installed or the model is not
    recognised as an OpenAI model.
    """
    # Only attempt tiktoken for OpenAI-style model names.
    openai_prefixes = ("gpt-", "text-", "code-", "o1", "o3", "o4")
    name_lower = model_name.lower()
    if not any(name_lower.startswith(p) for p in openai_prefixes):
        return None

    try:
        import tiktoken  # type: ignore[import-untyped]
    except ImportError:
        return None

    try:
        return tiktoken.encoding_for_model(model_name)  # type: ignore[return-value]
    except KeyError:
        pass
    try:
        return tiktoken.get_encoding("cl100k_base")  # type: ignore[return-value]
    except Exception:  # pragma: no cover
        return None


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
# Token estimation
# ---------------------------------------------------------------------------


def estimate_tokens(text: str, model_name: str = "") -> int:
    """Estimate token count from *text*.

    Resolution order:

    1. **tiktoken** (exact) — when *model_name* identifies an OpenAI model
       and ``tiktoken`` is installed.
    2. **Character ratio** — ``len(text) / CHARS_PER_TOKEN`` (minimum 1).

    Args:
        text: Input text to estimate.
        model_name: Optional model identifier used to select the tiktoken
            encoder.  When omitted or not an OpenAI model, falls back to
            the character-based heuristic.

    Returns:
        Estimated token count (always ≥ 1).
    """
    if model_name:
        enc = _get_tiktoken_encoder(model_name)
        if enc is not None:
            try:
                return max(1, len(enc.encode(text)))  # type: ignore[attr-defined]
            except Exception:
                pass  # fall through to char-based

    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_tokens_for_model(text: str, model_name: str) -> int:
    """Estimate token count, applying model-specific character ratios as fallback.

    For non-OpenAI models the ratio is chosen based on a heuristic: content
    with a high proportion of non-alphanumeric characters is treated as code
    (≈ 3.5 chars/token); otherwise natural-language ratio (≈ 4 chars/token) is
    used.

    Args:
        text: Input text to estimate.
        model_name: Model identifier (e.g. ``"gpt-4o"`` or
            ``"anthropic/claude-sonnet-4"``).

    Returns:
        Estimated token count (always ≥ 1).
    """
    if not text:
        return 1

    # Try tiktoken first (works for OpenAI models).
    enc = _get_tiktoken_encoder(model_name)
    if enc is not None:
        try:
            return max(1, len(enc.encode(text)))  # type: ignore[attr-defined]
        except Exception:
            pass

    # Character-based fallback with model-specific ratio.
    total = len(text)
    if total == 0:
        return 1
    non_alnum = sum(1 for ch in text if not ch.isalnum() and not ch.isspace())
    code_ratio = non_alnum / total
    ratio = CHARS_PER_TOKEN_CODE if code_ratio > 0.25 else CHARS_PER_TOKEN  # noqa: PLR2004
    return max(1, int(total / ratio))


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
