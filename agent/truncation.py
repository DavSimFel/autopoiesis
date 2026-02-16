"""Truncate large tool results and persist full output to disk.

Dependencies: pydantic_ai.messages
Wired in: chat.py → main() (as history_processor)
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart

DEFAULT_MAX_CHARS = 5000
"""Default character limit for tool result content."""


def _ensure_log_dir(workspace_root: Path) -> Path:
    """Create and return the tool-results log directory."""
    log_dir = workspace_root / ".tmp" / "tool-results"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _truncate_part(
    part: ToolReturnPart,
    log_dir: Path,
    max_chars: int,
) -> ToolReturnPart:
    """Truncate a single tool return part if its content exceeds *max_chars*."""
    content = part.content
    if not isinstance(content, str):
        return part
    if len(content) <= max_chars:
        return part

    log_path = log_dir / f"{part.tool_call_id}.log"
    log_path.write_text(content, encoding="utf-8")

    truncated = content[:max_chars]
    suffix = f"\n\n[Truncated — full output ({len(content)} chars) saved to {log_path}]"
    new_content = truncated + suffix
    return dataclasses.replace(part, content=new_content)


def truncate_tool_results(
    messages: list[ModelMessage],
    workspace_root: Path,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[ModelMessage]:
    """Truncate tool return parts that exceed *max_chars*.

    Full output is saved to ``.tmp/tool-results/<call-id>.log`` under
    *workspace_root* and the message content is replaced with a
    truncated version plus a file-path reference.

    Args:
        messages: Conversation history (a new list is returned).
        workspace_root: Root directory for persisting full results.
        max_chars: Maximum characters per tool result before truncation.

    Returns:
        The (possibly modified) message list.
    """
    log_dir: Path | None = None
    result: list[ModelMessage] = []

    for msg in messages:
        if not isinstance(msg, ModelRequest):
            result.append(msg)
            continue

        needs_update = any(
            isinstance(p, ToolReturnPart)
            and isinstance(p.content, str)
            and len(p.content) > max_chars
            for p in msg.parts
        )
        if not needs_update:
            result.append(msg)
            continue

        if log_dir is None:
            log_dir = _ensure_log_dir(workspace_root)

        new_parts = [
            _truncate_part(p, log_dir, max_chars) if isinstance(p, ToolReturnPart) else p
            for p in msg.parts
        ]
        result.append(dataclasses.replace(msg, parts=new_parts))

    return result
