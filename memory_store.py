"""SQLite FTS5-backed persistent memory store for cross-session knowledge.

Provides structured memory entries stored in SQLite with full-text search via
FTS5, plus unstructured workspace memory file searching. Zero external
dependencies — uses only stdlib sqlite3.
"""

from __future__ import annotations

import logging
import re
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from db import open_db

logger = logging.getLogger(__name__)

_DEFAULT_MEMORY_DB_PATH = Path(__file__).resolve().parent / "data" / "memory.sqlite"

_CREATE_ENTRIES_SQL = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    topics TEXT NOT NULL DEFAULT '',
    raw_history_json TEXT NOT NULL DEFAULT '{}'
);
"""

_CREATE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
USING fts5(summary, topics, content='memory_entries', content_rowid='rowid');
"""

_CREATE_TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_entries BEGIN
    INSERT INTO memory_fts(rowid, summary, topics)
    VALUES (new.rowid, new.summary, new.topics);
END;

CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, summary, topics)
    VALUES ('delete', old.rowid, old.summary, old.topics);
END;

CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, summary, topics)
    VALUES ('delete', old.rowid, old.summary, old.topics);
    INSERT INTO memory_fts(rowid, summary, topics)
    VALUES (new.rowid, new.summary, new.topics);
END;
"""


def resolve_memory_db_path(dbos_db_url: str) -> str:
    """Derive memory store path from the DBOS system database URL."""
    if dbos_db_url.startswith("sqlite:///"):
        raw_path = dbos_db_url.removeprefix("sqlite:///").split("?", 1)[0]
        if raw_path and raw_path != ":memory:":
            source = Path(raw_path)
            suffix = source.suffix or ".sqlite"
            return str(source.with_name(f"{source.stem}_memory{suffix}"))
    return str(_DEFAULT_MEMORY_DB_PATH)


def _ensure_parent_dir(db_path: str) -> None:
    """Ensure the SQLite file's parent directory exists."""
    Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def init_memory_store(db_path: str) -> None:
    """Create tables, FTS5 virtual table, and sync triggers."""
    _ensure_parent_dir(db_path)
    with closing(open_db(Path(db_path))) as conn, conn:
        conn.execute(_CREATE_ENTRIES_SQL)
        conn.execute(_CREATE_FTS_SQL)
        conn.executescript(_CREATE_TRIGGERS_SQL)
        conn.commit()


def save_memory(
    db_path: str,
    summary: str,
    topics: list[str],
    session_id: str = "",
    raw_history_json: str = "{}",
) -> str:
    """Insert a memory entry and return its id."""
    entry_id = uuid4().hex
    now = datetime.now(UTC).isoformat()
    topics_str = ",".join(topics)
    _ensure_parent_dir(db_path)
    with closing(open_db(Path(db_path))) as conn, conn:
        conn.execute(
            """
            INSERT INTO memory_entries
                (id, timestamp, session_id, summary, topics, raw_history_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry_id, now, session_id, summary, topics_str, raw_history_json),
        )
        conn.commit()
    return entry_id


def search_memory(
    db_path: str,
    query: str,
    max_results: int = 5,
) -> list[dict[str, str]]:
    """Search memory entries via FTS5, returning ranked results."""
    _ensure_parent_dir(db_path)
    fts_query = _sanitize_fts_query(query)
    if not fts_query:
        return []
    with closing(open_db(Path(db_path))) as conn, conn:
        rows = conn.execute(
            """
            SELECT e.id, e.timestamp, e.session_id, e.summary, e.topics
            FROM memory_fts f
            JOIN memory_entries e ON f.rowid = e.rowid
            WHERE memory_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, max_results),
        ).fetchall()
    return [dict(row) for row in rows]


def _sanitize_fts_query(query: str) -> str:
    """Sanitize user input into a safe FTS5 query string.

    Strips FTS5 operators/special chars and wraps each token as a prefix
    search term.  FTS5 keywords (AND, OR, NOT, NEAR) are dropped because
    they alter query semantics even when suffixed with ``*``.
    """
    fts5_keywords = {"AND", "OR", "NOT", "NEAR"}
    cleaned = re.sub(r"[^\w\s]", " ", query)
    tokens = [t for t in cleaned.split() if t.upper() not in fts5_keywords]
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens)


def search_memory_files(
    workspace_root: Path,
    query: str,
    max_results: int = 5,
) -> list[dict[str, str]]:
    """Search workspace memory files for lines matching query tokens."""
    tokens = query.lower().split()
    if not tokens:
        return []

    candidates: list[Path] = []
    memory_md = workspace_root / "MEMORY.md"
    if memory_md.is_file():
        candidates.append(memory_md)
    memory_dir = workspace_root / "memory"
    if memory_dir.is_dir():
        candidates.extend(sorted(memory_dir.glob("*.md")))

    results: list[dict[str, str]] = []
    for filepath in candidates:
        matches = _search_single_file(filepath, tokens, workspace_root)
        results.extend(matches)
        if len(results) >= max_results:
            break
    return results[:max_results]


def _search_single_file(
    filepath: Path,
    tokens: list[str],
    workspace_root: Path,
) -> list[dict[str, str]]:
    """Return matching context snippets from a single file."""
    try:
        lines = filepath.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        logger.warning("Failed to read memory file %s", filepath)
        return []

    matches: list[dict[str, str]] = []
    relative = str(filepath.relative_to(workspace_root))
    for i, line in enumerate(lines):
        lower_line = line.lower()
        if any(token in lower_line for token in tokens):
            start = max(0, i - 1)
            end = min(len(lines), i + 2)
            snippet = "\n".join(lines[start:end])
            matches.append(
                {
                    "file": relative,
                    "line": str(i + 1),
                    "snippet": snippet,
                }
            )
    return matches


def get_memory_file_snippet(
    workspace_root: Path,
    path: str,
    from_line: int | None = None,
    num_lines: int | None = None,
) -> str:
    """Read a snippet from a workspace memory file."""
    resolved = (workspace_root / path).resolve()
    if not resolved.is_relative_to(workspace_root.resolve()):
        return "Error: path escapes workspace root."
    if not resolved.is_file():
        return f"Error: file not found: {path}"
    try:
        all_lines = resolved.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return f"Error: could not read {path}"
    start = (from_line - 1) if from_line and from_line > 0 else 0
    end = (start + num_lines) if num_lines and num_lines > 0 else len(all_lines)
    selected = all_lines[start:end]
    return "\n".join(selected)


def combined_search(
    db_path: str,
    workspace_root: Path,
    query: str,
    max_results: int = 5,
) -> str:
    """Search both SQLite FTS5 and workspace memory files, return formatted."""
    db_results = search_memory(db_path, query, max_results)
    file_results = search_memory_files(workspace_root, query, max_results)

    parts: list[str] = []
    if db_results:
        parts.append("## Database matches")
        for entry in db_results:
            parts.append(f"- [{entry['timestamp']}] {entry['summary']} (topics: {entry['topics']})")
    if file_results:
        parts.append("## File matches")
        for match in file_results:
            parts.append(f"- {match['file']}:{match['line']}\n  {match['snippet']}")
    if not parts:
        parts.append("No memory matches found.")
    return "\n".join(parts)
