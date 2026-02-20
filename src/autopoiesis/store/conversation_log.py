"""Conversation turn logging for T2 reflection and analysis.

Each conversation turn is appended to a daily markdown log file under
``knowledge/logs/{agent_id}/YYYY-MM-DD.md``.  These files are then
indexed into the existing FTS5 knowledge system so that T2 agents can
search and analyse T1's conversation history.

Entry format (one per ModelRequest / ModelResponse in the turn):

    ## 2026-02-20T14:39:00.123456+00:00

    - **user**: First 200 chars of the user message...
    - **assistant**: Summary of assistant reply *(tools: search_knowledge, web_search)*

Log rotation removes files whose date is older than the configured
*retention_days* ceiling.

Dependencies: pydantic_ai.messages, store.knowledge
Wired in: agent/worker.py → run_agent_step()
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)

from autopoiesis.store.knowledge import index_file, init_knowledge_index

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUMMARY_MAX_CHARS = 200
"""Maximum characters kept for content summaries in log entries."""

_LOG_SUBDIR = "logs"
"""Sub-directory under knowledge_root where agent log dirs live."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _summarize(text: str, max_chars: int = _SUMMARY_MAX_CHARS) -> str:
    """Truncate *text* to *max_chars* with an ellipsis if needed."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _extract_content(part: object) -> str:
    """Return the text content of a message part, or empty string."""
    if isinstance(part, (UserPromptPart, SystemPromptPart, TextPart)):
        content = part.content
        if isinstance(content, str):
            return content
        # UserPromptPart can hold arbitrary content (e.g. list of parts)
        return str(content)
    return ""


def _parse_messages(
    messages: list[ModelMessage],
) -> list[tuple[str, str, list[str]]]:
    """Convert *messages* into (role, summary, tool_names) triples.

    Roles are ``"user"``, ``"system"``, or ``"assistant"``.
    Tool names are collected from :class:`~pydantic_ai.messages.ToolCallPart`
    objects only — results are deliberately excluded (too large).
    """
    entries: list[tuple[str, str, list[str]]] = []

    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    entries.append(("user", _summarize(_extract_content(part)), []))
                elif isinstance(part, SystemPromptPart):
                    entries.append(("system", _summarize(_extract_content(part)), []))
                # ToolReturnPart is a request part but we skip it (it's a result)

        elif isinstance(msg, ModelResponse):
            tool_names: list[str] = []
            text_parts: list[str] = []
            for part in msg.parts:
                if isinstance(part, TextPart):
                    text_parts.append(_extract_content(part))
                elif isinstance(part, ToolCallPart):
                    tool_names.append(part.tool_name)
            summary = _summarize(" ".join(text_parts))
            entries.append(("assistant", summary, tool_names))

    return entries


def _format_entry(
    timestamp: datetime,
    entries: list[tuple[str, str, list[str]]],
) -> str:
    """Render a single turn block as a markdown string."""
    lines: list[str] = [f"## {timestamp.isoformat()}", ""]
    for role, summary, tools in entries:
        if tools:
            tool_str = f" *(tools: {', '.join(tools)})*"
        else:
            tool_str = ""
        lines.append(f"- **{role}**: {summary}{tool_str}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Log directory helpers
# ---------------------------------------------------------------------------


def _log_dir(knowledge_root: Path, agent_id: str) -> Path:
    """Return the log directory for *agent_id* (not yet created)."""
    return knowledge_root / _LOG_SUBDIR / agent_id


def _log_file(knowledge_root: Path, agent_id: str, date: str) -> Path:
    """Return the log file path for *agent_id* on *date* (``YYYY-MM-DD``)."""
    return _log_dir(knowledge_root, agent_id) / f"{date}.md"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def append_turn(
    knowledge_root: Path,
    knowledge_db_path: str,
    agent_id: str,
    messages: list[ModelMessage],
    *,
    timestamp: datetime | None = None,
) -> Path | None:
    """Append one conversation turn to the agent's daily log file.

    Parses *messages* to extract role, content summary, and tool call names,
    then appends a formatted markdown block to the daily file.  The file is
    subsequently re-indexed in the FTS5 knowledge database.

    Parameters
    ----------
    knowledge_root:
        Root of the knowledge directory tree (``AgentPaths.knowledge``).
    knowledge_db_path:
        Path to the SQLite knowledge index database.
    agent_id:
        Unique agent identifier used to scope the log directory.
    messages:
        All messages from the completed turn (as returned by pydantic-ai).
    timestamp:
        Override for the log entry timestamp (defaults to ``datetime.now(UTC)``).

    Returns
    -------
    Path | None
        The log file that was written to, or ``None`` if *messages* is empty.
    """
    if not messages:
        return None

    ts = timestamp or datetime.now(UTC)
    date_str = ts.strftime("%Y-%m-%d")

    log_path = _log_file(knowledge_root, agent_id, date_str)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entries = _parse_messages(messages)
    if not entries:
        return None

    block = _format_entry(ts, entries)

    # Append to daily file (create with header if new)
    if not log_path.exists():
        header = f"# Conversation log — {agent_id} — {date_str}\n\n"
        log_path.write_text(header + block, encoding="utf-8")
    else:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(block)

    # Index (or re-index) the updated file in the FTS5 knowledge database.
    try:
        init_knowledge_index(knowledge_db_path)
        index_file(knowledge_db_path, knowledge_root, log_path)
    except Exception:
        logger.warning("Failed to index conversation log %s", log_path, exc_info=True)

    return log_path


def rotate_logs(
    knowledge_root: Path,
    agent_id: str,
    retention_days: int,
) -> list[Path]:
    """Delete log files older than *retention_days* for *agent_id*.

    Parameters
    ----------
    knowledge_root:
        Root of the knowledge directory tree.
    agent_id:
        Agent whose logs should be rotated.
    retention_days:
        Files whose date is strictly older than this many days are removed.
        When *retention_days* is ``0`` or negative, nothing is deleted.

    Returns
    -------
    list[Path]
        Paths of files that were deleted.
    """
    if retention_days <= 0:
        return []

    cutoff = datetime.now(UTC).date() - timedelta(days=retention_days)
    log_dir = _log_dir(knowledge_root, agent_id)

    if not log_dir.is_dir():
        return []

    deleted: list[Path] = []
    for log_file in log_dir.glob("*.md"):
        stem = log_file.stem  # "YYYY-MM-DD"
        try:
            file_date = datetime.strptime(stem, "%Y-%m-%d").date()
        except ValueError:
            continue  # skip files with unexpected names
        if file_date < cutoff:
            try:
                log_file.unlink()
                deleted.append(log_file)
                logger.debug("Rotated old conversation log: %s", log_file)
            except OSError:
                logger.warning("Failed to delete old log file: %s", log_file, exc_info=True)

    return deleted
