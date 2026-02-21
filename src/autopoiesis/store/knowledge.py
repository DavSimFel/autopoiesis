"""File-based knowledge management with FTS5 search indexing.

Files in the ``knowledge/`` directory are the source of truth.  SQLite FTS5
provides a search index that is rebuilt from files — never the other way around.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from autopoiesis.db import open_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type registry
# ---------------------------------------------------------------------------

_BUILTIN_TYPES = frozenset(
    {"fact", "experience", "preference", "note", "conversation", "decision", "contact", "project"}
)

_registered_types: set[str] = set()


def register_types(types: set[str]) -> None:
    """Register additional memory types (e.g. from skills at startup)."""
    _registered_types.update(types)


def known_types() -> frozenset[str]:
    """Return all known memory types (built-in + registered)."""
    return _BUILTIN_TYPES | frozenset(_registered_types)


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.DOTALL)


@dataclass
class FileMeta:
    """Parsed frontmatter metadata for a knowledge file."""

    type: str = "note"
    created: datetime = field(default_factory=lambda: datetime.now(UTC))
    modified: datetime = field(default_factory=lambda: datetime.now(UTC))


def _parse_datetime(val: object) -> datetime | None:
    """Try to interpret *val* as a timezone-aware datetime."""
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=UTC)
    if isinstance(val, str):
        try:
            parsed = datetime.fromisoformat(val)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def parse_frontmatter(content: str, file_path: Path | None = None) -> FileMeta:
    """Extract ``type``, ``created``, ``modified`` from YAML frontmatter.

    Falls back to file mtime when fields are missing or frontmatter is absent.
    Unknown types are treated as ``note``.
    """
    meta = FileMeta()

    # Derive defaults from file mtime if available
    if file_path is not None and file_path.is_file():
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
        meta.created = mtime
        meta.modified = mtime

    m = _FRONTMATTER_RE.match(content)
    if m is None:
        return meta

    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return meta

    if not isinstance(data, dict):
        return meta

    fm = cast(dict[str, Any], data)

    raw_type = fm.get("type")
    if isinstance(raw_type, str) and raw_type in known_types():
        meta.type = raw_type

    for key in ("created", "modified"):
        dt = _parse_datetime(fm.get(key))
        if dt is not None:
            setattr(meta, key, dt)

    return meta


def strip_frontmatter(content: str) -> str:
    """Return *content* without the leading YAML frontmatter block."""
    return _FRONTMATTER_RE.sub("", content)


# ---------------------------------------------------------------------------
# Wikilink backlink index
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")


def build_backlink_index(knowledge_root: Path) -> dict[str, set[str]]:
    """Scan all markdown files for ``[[target]]`` wikilinks.

    Returns a mapping from *target* (lowercased, no extension) to the set of
    source file paths (relative to *knowledge_root*) that link to it.
    """
    index: dict[str, set[str]] = {}
    if not knowledge_root.is_dir():
        return index

    root_str = str(knowledge_root)
    finditer = _WIKILINK_RE.finditer

    for dirpath, _dirnames, filenames in os.walk(root_str):
        for filename in filenames:
            if not filename.endswith(".md"):
                continue
            md = os.path.join(dirpath, filename)
            rel = os.path.relpath(md, root_str)
            try:
                with open(md, encoding="utf-8") as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            if "[[" not in text:
                continue

            for match in finditer(text):
                target = match.group(1).strip().lower()
                if not target:
                    continue
                sources = index.get(target)
                if sources is None:
                    index[target] = {rel}
                else:
                    sources.add(rel)

    return index


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_CHUNKS_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    modified_at TEXT NOT NULL,
    UNIQUE(file_path, chunk_index)
);
"""

_CREATE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
USING fts5(content, file_path, content='knowledge_chunks', content_rowid='id');
"""

_CREATE_TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS kc_ai AFTER INSERT ON knowledge_chunks BEGIN
    INSERT INTO knowledge_fts(rowid, content, file_path)
    VALUES (new.id, new.content, new.file_path);
END;

CREATE TRIGGER IF NOT EXISTS kc_ad AFTER DELETE ON knowledge_chunks BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, content, file_path)
    VALUES ('delete', old.id, old.content, old.file_path);
END;

CREATE TRIGGER IF NOT EXISTS kc_au AFTER UPDATE ON knowledge_chunks BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, content, file_path)
    VALUES ('delete', old.id, old.content, old.file_path);
    INSERT INTO knowledge_fts(rowid, content, file_path)
    VALUES (new.id, new.content, new.file_path);
END;
"""

_CREATE_FILE_META_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_file_meta (
    file_path TEXT PRIMARY KEY,
    modified_at TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHUNK_SIZE_LINES = 30
"""Number of lines per chunk when splitting files for indexing."""

CONTEXT_BUDGET_CHARS = 25_000
"""Maximum characters of auto-loaded context (~25 KB for ASCII)."""

_JOURNAL_TEMPLATE = """\
# {date}

<!-- Daily notes. Write observations, decisions, and things to remember. -->
"""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A single search hit from the knowledge index."""

    file_path: str
    line_start: int
    line_end: int
    snippet: str
    score: float
    file_type: str = "note"


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------


def init_knowledge_index(db_path: str) -> None:
    """Create the knowledge index tables and triggers."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(open_db(Path(db_path))) as conn, conn:
        conn.execute(_CREATE_CHUNKS_SQL)
        conn.execute(_CREATE_FTS_SQL)
        conn.executescript(_CREATE_TRIGGERS_SQL)
        conn.execute(_CREATE_FILE_META_SQL)
        conn.commit()


def _chunk_file(lines: list[str], chunk_size: int = CHUNK_SIZE_LINES) -> list[tuple[int, int, str]]:
    """Split lines into chunks, returning (line_start, line_end, content)."""
    chunks: list[tuple[int, int, str]] = []
    for i in range(0, len(lines), chunk_size):
        batch = lines[i : i + chunk_size]
        chunks.append((i + 1, i + len(batch), "\n".join(batch)))
    return chunks


def index_file(db_path: str, knowledge_root: Path, file_path: Path) -> None:
    """Index or re-index a single markdown file."""
    rel = str(file_path.relative_to(knowledge_root))
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning("Cannot read %s for indexing", file_path)
        return

    mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC).isoformat()
    now = datetime.now(UTC).isoformat()
    lines = content.splitlines()
    chunks = _chunk_file(lines)

    with closing(open_db(Path(db_path))) as conn, conn:
        conn.execute("DELETE FROM knowledge_chunks WHERE file_path = ?", (rel,))
        for idx, (line_start, line_end, chunk_content) in enumerate(chunks):
            conn.execute(
                """INSERT INTO knowledge_chunks
                   (file_path, chunk_index, content, line_start, line_end, modified_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (rel, idx, chunk_content, line_start, line_end, mtime),
            )
        conn.execute(
            """INSERT OR REPLACE INTO knowledge_file_meta (file_path, modified_at, indexed_at)
               VALUES (?, ?, ?)""",
            (rel, mtime, now),
        )
        conn.commit()


def reindex_knowledge(db_path: str, knowledge_root: Path) -> int:
    """Incrementally re-index all markdown files under *knowledge_root*.

    Only re-indexes files whose mtime has changed since last indexing.
    Removes index entries for deleted files.  Returns the number of files
    re-indexed.
    """
    if not knowledge_root.is_dir():
        return 0

    current_files: dict[str, Path] = {}
    for md_file in knowledge_root.rglob("*.md"):
        rel = str(md_file.relative_to(knowledge_root))
        current_files[rel] = md_file

    # Load existing file metadata
    indexed_meta: dict[str, str] = {}
    with closing(open_db(Path(db_path))) as conn:
        for row in conn.execute("SELECT file_path, modified_at FROM knowledge_file_meta"):
            indexed_meta[row["file_path"]] = row["modified_at"]

    # Remove deleted files from the index
    deleted = set(indexed_meta) - set(current_files)
    if deleted:
        with closing(open_db(Path(db_path))) as conn, conn:
            for rel in deleted:
                conn.execute("DELETE FROM knowledge_chunks WHERE file_path = ?", (rel,))
                conn.execute("DELETE FROM knowledge_file_meta WHERE file_path = ?", (rel,))
            conn.commit()

    # Index new or modified files
    reindexed = 0
    for rel, filepath in current_files.items():
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=UTC).isoformat()
        if rel in indexed_meta and indexed_meta[rel] == mtime:
            continue
        index_file(db_path, knowledge_root, filepath)
        reindexed += 1

    return reindexed


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

_FTS5_KEYWORDS = frozenset({"AND", "OR", "NOT", "NEAR"})


def sanitize_fts_query(query: str) -> str:
    """Turn user input into a safe FTS5 query string."""
    cleaned = re.sub(r"[^\w\s]", " ", query)
    tokens = [t for t in cleaned.split() if t.upper() not in _FTS5_KEYWORDS]
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens)


def search_knowledge(
    db_path: str,
    query: str,
    limit: int = 10,
    *,
    type_filter: str | None = None,
    since: datetime | None = None,
    knowledge_root: Path | None = None,
) -> list[SearchResult]:
    """Search the knowledge index using FTS5 BM25 ranking.

    Optional filters:

    * *type_filter* - only return results from files whose frontmatter
      ``type`` matches (requires *knowledge_root*).
    * *since* - only return results from files created or modified on/after
      this datetime (requires *knowledge_root*).
    """
    fts_query = sanitize_fts_query(query)
    if not fts_query:
        return []
    with closing(open_db(Path(db_path))) as conn:
        rows = conn.execute(
            """
            SELECT c.file_path, c.line_start, c.line_end, c.content,
                   rank AS score
            FROM knowledge_fts f
            JOIN knowledge_chunks c ON f.rowid = c.id
            WHERE knowledge_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit * 5 if (type_filter or since) else limit),
        ).fetchall()

    results: list[SearchResult] = []
    _meta_cache: dict[str, FileMeta] = {}

    for row in rows:
        fp = row["file_path"]

        if (type_filter or since) and knowledge_root is not None:
            if fp not in _meta_cache:
                abs_path = knowledge_root / fp
                try:
                    content = abs_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    content = ""
                _meta_cache[fp] = parse_frontmatter(content, abs_path)

            meta = _meta_cache[fp]

            if type_filter and meta.type != type_filter:
                continue
            if since and meta.created < since and meta.modified < since:
                continue

        results.append(
            SearchResult(
                file_path=fp,
                line_start=row["line_start"],
                line_end=row["line_end"],
                snippet=row["content"][:500],
                score=float(row["score"]),
            )
        )
        if len(results) >= limit:
            break

    return results


def format_search_results(results: list[SearchResult]) -> str:
    """Format search results into a human-readable string."""
    if not results:
        return "No results found."
    parts: list[str] = []
    for r in results:
        parts.append(f"**{r.file_path}** (lines {r.line_start}-{r.line_end}):\n{r.snippet}")
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Context injection
# ---------------------------------------------------------------------------

_IDENTITY_FILES = (
    "identity/SOUL.md",
    "identity/USER.md",
    "identity/AGENTS.md",
    "identity/TOOLS.md",
)

_SESSION_FILES = ("memory/MEMORY.md",)


def _read_capped(path: Path, remaining: int) -> tuple[str, int]:
    """Read a file up to *remaining* bytes.  Returns (content, bytes_used)."""
    if not path.is_file() or remaining <= 0:
        return "", 0
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "", 0
    if len(text) > remaining:
        text = text[:remaining] + "\n[…truncated to fit context budget]"
    used = len(text)
    return text, used


def load_knowledge_context(knowledge_root: Path) -> str:
    """Load identity + session files respecting the ~25 KB budget.

    Returns a single string suitable for prepending to the system prompt.
    """
    if not knowledge_root.is_dir():
        return ""

    budget = CONTEXT_BUDGET_CHARS
    sections: list[str] = []

    # Identity files (always loaded)
    for rel in _IDENTITY_FILES:
        text, used = _read_capped(knowledge_root / rel, budget)
        if text:
            sections.append(text)
            budget -= used

    # Session files
    for rel in _SESSION_FILES:
        text, used = _read_capped(knowledge_root / rel, budget)
        if text:
            sections.append(text)
            budget -= used

    # Today's journal entry
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    journal_path = knowledge_root / "journal" / f"{today}.md"
    text, used = _read_capped(journal_path, budget)
    if text:
        sections.append(text)
        budget -= used

    return "\n\n---\n\n".join(sections) if sections else ""


# ---------------------------------------------------------------------------
# Journal helpers
# ---------------------------------------------------------------------------


def ensure_journal_entry(knowledge_root: Path) -> Path:
    """Create today's journal file if it doesn't exist yet. Returns its path."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    journal_dir = knowledge_root / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal_path = journal_dir / f"{today}.md"
    if not journal_path.exists():
        journal_path.write_text(_JOURNAL_TEMPLATE.format(date=today), encoding="utf-8")
    return journal_path


# Migration logic lives in store/knowledge_migration.py
