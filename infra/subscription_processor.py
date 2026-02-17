"""History processor that materializes subscriptions before each agent turn.

Resolves all active subscriptions to their current content and injects
a ``ModelRequest`` with the materialized text right before the final
user message.  Old materialization messages are stripped first so
content is always fresh.

Dependencies: store.knowledge, store.subscriptions
Wired in: chat.py → main() (as history_processor)
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    UserPromptPart,
)

from store.knowledge import search_knowledge
from store.subscriptions import (
    MaterializedContent,
    Subscription,
    SubscriptionRegistry,
    content_hash,
    truncate_content,
)

logger = logging.getLogger(__name__)

_MATERIALIZATION_TAG = "materialized_subscriptions"
_PATTERN_CACHE_SIZE = 128


@lru_cache(maxsize=_PATTERN_CACHE_SIZE)
def _compile_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def is_materialization(msg: ModelMessage) -> bool:
    """Return True if *msg* is a previous materialization injection."""
    if not isinstance(msg, ModelRequest):
        return False
    meta = msg.metadata
    if meta is None:
        return False
    return _MATERIALIZATION_TAG in meta


def _read_file(target: str, workspace_root: Path, sub: Subscription) -> str:
    """Read file content, optionally slicing by line range."""
    resolved = (workspace_root / target).resolve()
    if not resolved.is_relative_to(workspace_root.resolve()):
        return "Error: path escapes workspace root."
    if not resolved.is_file():
        return f"Error: file not found: {target}"
    try:
        lines = resolved.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return f"Error: could not read {target}"
    if sub.line_range is not None:
        start = max(0, sub.line_range[0] - 1)
        end = sub.line_range[1]
        lines = lines[start:end]
    if sub.pattern is not None:
        try:
            regex = _compile_pattern(sub.pattern)
        except re.error:
            return f"Error: invalid pattern: {sub.pattern}"
        lines = [ln for ln in lines if regex.search(ln)]
    return "\n".join(lines)


def _read_knowledge(
    target: str,
    knowledge_db_path: str,
) -> str:
    """Run a knowledge FTS5 query and format top results."""
    results = search_knowledge(knowledge_db_path, target, limit=5)
    if not results:
        return "(no matches)"
    parts: list[str] = []
    for entry in results:
        parts.append(f"- {entry.file_path}:{entry.line_start}-{entry.line_end}\n  {entry.snippet}")
    return "\n".join(parts)


def _resolve_one(
    sub: Subscription,
    workspace_root: Path,
    knowledge_db_path: str,
) -> MaterializedContent:
    """Resolve a single subscription to its current content."""
    if sub.kind in ("file", "lines"):
        raw = _read_file(sub.target, workspace_root, sub)
    else:
        raw = _read_knowledge(sub.target, knowledge_db_path)
    truncated = truncate_content(raw)
    header = f"[📎 {sub.target}]"
    if sub.line_range is not None:
        header += f" (lines {sub.line_range[0]}-{sub.line_range[1]})"
    return MaterializedContent(
        subscription=sub,
        header=header,
        content=truncated,
        content_hash=content_hash(truncated),
    )


def resolve_subscriptions(
    registry: SubscriptionRegistry,
    workspace_root: Path,
    knowledge_db_path: str,
) -> list[MaterializedContent]:
    """Resolve all active subscriptions to materialized content."""
    active = registry.get_active()
    results: list[MaterializedContent] = []
    for sub in active:
        mat = _resolve_one(sub, workspace_root, knowledge_db_path)
        registry.update_hash(sub.id, mat.content_hash)
        results.append(mat)
    return results


def materialize_subscriptions(
    messages: list[ModelMessage],
    registry: SubscriptionRegistry,
    workspace_root: Path,
    knowledge_db_path: str,
) -> list[ModelMessage]:
    """History processor: inject materialized subscription content.

    1. Strip old materialization messages
    2. Resolve all active subscriptions
    3. Insert a materialization ``ModelRequest`` before the last message
    """
    cleaned = [m for m in messages if not is_materialization(m)]
    materialized = resolve_subscriptions(
        registry,
        workspace_root,
        knowledge_db_path,
    )
    non_empty = [m for m in materialized if m.content.strip()]
    if not non_empty:
        return cleaned

    parts: list[UserPromptPart] = []
    hashes: dict[str, str] = {}
    for mat in non_empty:
        parts.append(
            UserPromptPart(
                content=f"{mat.header}\n{mat.content}",
            )
        )
        hashes[mat.subscription.id] = mat.content_hash

    mat_msg = ModelRequest(
        parts=parts,
        metadata={
            _MATERIALIZATION_TAG: list(hashes.keys()),
            "materialization_hashes": hashes,
        },
    )
    # Insert before the final message so subscriptions appear
    # right before the latest user prompt.
    insert_pos = max(0, len(cleaned) - 1)
    cleaned.insert(insert_pos, mat_msg)
    return cleaned
