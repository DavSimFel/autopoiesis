"""Token estimation utilities for context window management.

Provides character-based and tiktoken-based token count estimation,
used by :mod:`autopoiesis.agent.context` for compaction decisions.

Dependencies: (stdlib only; tiktoken optional)
Wired in: context.py → estimate_tokens, estimate_tokens_for_model
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Character-to-token ratios
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN = 4
"""Default character-to-token ratio (natural language, ~4 chars/token)."""

CHARS_PER_TOKEN_CODE = 3.5
"""Character-to-token ratio for code-heavy content (~3.5 chars/token)."""


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
            except Exception:  # nosec B110
                pass

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
        except Exception:  # nosec B110
            pass

    # Character-based fallback with model-specific ratio.
    total = len(text)
    if total == 0:
        return 1
    non_alnum = sum(1 for ch in text if not ch.isalnum() and not ch.isspace())
    code_ratio = non_alnum / total
    ratio = CHARS_PER_TOKEN_CODE if code_ratio > 0.25 else CHARS_PER_TOKEN  # noqa: PLR2004
    return max(1, int(total / ratio))
