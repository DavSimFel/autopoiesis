"""Truncate large tool results and persist full output to disk.

Dependencies: pydantic_ai.messages
Wired in: agent/history.py → build_history_processors()
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart

DEFAULT_MAX_BYTES = 10 * 1024
"""Default byte limit for tool result content (10 KB)."""

# Keep the old name as an alias so existing call-sites that import
# ``DEFAULT_MAX_CHARS`` continue to work without changes.
DEFAULT_MAX_CHARS = DEFAULT_MAX_BYTES


def _get_max_tool_result_bytes() -> int:
    """Read per-tool-result byte cap from the environment.

    The environment variable ``TOOL_RESULT_MAX_BYTES`` overrides the default
    10 KB cap.  When the variable is absent or blank the default is used.
    """
    raw = os.getenv("TOOL_RESULT_MAX_BYTES", "")
    if not raw.strip():
        return DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except ValueError:
        msg = f"TOOL_RESULT_MAX_BYTES must be an integer, got {raw!r}"
        raise ValueError(msg) from None
    if value <= 0:
        msg = f"TOOL_RESULT_MAX_BYTES must be positive, got {value}"
        raise ValueError(msg)
    return value


def _ensure_log_dir(workspace_root: Path) -> Path:
    """Create and return the tool-results log directory."""
    log_dir = workspace_root / ".tmp" / "tool-results"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def cap_tool_result(
    content: str,
    max_bytes: int,
) -> str:
    """Truncate *content* to at most *max_bytes* bytes with a marker suffix.

    The truncation marker format is::

        [truncated: {original_size} -> {truncated_size}]

    where both sizes are in bytes.

    Args:
        content: Raw tool result string.
        max_bytes: Maximum allowed size in bytes.

    Returns:
        The original string if within the cap, otherwise a truncated
        version with the marker appended.
    """
    encoded = content.encode("utf-8", errors="replace")
    original_size = len(encoded)
    if original_size <= max_bytes:
        return content

    # Decode the first max_bytes safely (avoid splitting a multibyte codepoint).
    truncated_bytes = encoded[:max_bytes]
    truncated_str = truncated_bytes.decode("utf-8", errors="replace")
    truncated_size = len(truncated_bytes)
    marker = f"\n[truncated: {original_size} -> {truncated_size}]"
    return truncated_str + marker


def _truncate_part(
    part: ToolReturnPart,
    log_dir: Path,
    max_bytes: int,
) -> ToolReturnPart:
    """Truncate a single tool return part if its content exceeds *max_bytes*."""
    content = part.content
    if not isinstance(content, str):
        return part

    encoded = content.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return part

    # Persist full output for post-hoc inspection.
    log_path = log_dir / f"{part.tool_call_id}.log"
    log_path.write_text(content, encoding="utf-8")

    new_content = cap_tool_result(content, max_bytes)
    return dataclasses.replace(part, content=new_content)


def truncate_tool_results(
    messages: list[ModelMessage],
    workspace_root: Path,
    max_chars: int | None = None,
) -> list[ModelMessage]:
    """Truncate tool return parts that exceed the configured byte cap.

    Full output is saved to ``.tmp/tool-results/<call-id>.log`` under
    *workspace_root* and the message content is replaced with a truncated
    version bearing the marker ``[truncated: {original_size} -> {truncated_size}]``.

    The cap is resolved in this order:

    1. *max_chars* argument (kept for backward compatibility — treated as bytes).
    2. ``TOOL_RESULT_MAX_BYTES`` environment variable.
    3. :data:`DEFAULT_MAX_BYTES` (10 KB).

    Args:
        messages: Conversation history (a new list is returned).
        workspace_root: Root directory for persisting full results.
        max_chars: Optional byte cap override (deprecated name kept for
            backward compatibility).

    Returns:
        The (possibly modified) message list.
    """
    max_bytes: int = max_chars if max_chars is not None else _get_max_tool_result_bytes()
    log_dir: Path | None = None
    result: list[ModelMessage] = []

    for msg in messages:
        if not isinstance(msg, ModelRequest):
            result.append(msg)
            continue

        needs_update = any(
            isinstance(p, ToolReturnPart)
            and isinstance(p.content, str)
            and len(p.content.encode("utf-8", errors="replace")) > max_bytes
            for p in msg.parts
        )
        if not needs_update:
            result.append(msg)
            continue

        if log_dir is None:
            log_dir = _ensure_log_dir(workspace_root)

        new_parts = [
            _truncate_part(p, log_dir, max_bytes) if isinstance(p, ToolReturnPart) else p
            for p in msg.parts
        ]
        result.append(dataclasses.replace(msg, parts=new_parts))

    return result
