"""SQLite-backed checkpoint store for durable agent message history."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from db import open_db

_CHECKPOINT_VERSION = 1
_DEFAULT_HISTORY_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "history.sqlite"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_history_checkpoints (
    work_item_id TEXT PRIMARY KEY,
    history_json TEXT NOT NULL,
    round_count INTEGER NOT NULL DEFAULT 0,
    checkpoint_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
"""


def resolve_history_db_path(dbos_db_url: str) -> str:
    """Derive the history store path from the DBOS system database URL.

    ``sqlite:///path/to/db.sqlite`` maps to ``path/to/db_history.sqlite``.
    Non-SQLite URLs fall back to a local SQLite file at ``data/history.sqlite``.
    """
    if dbos_db_url.startswith("sqlite:///"):
        raw_path = dbos_db_url.removeprefix("sqlite:///").split("?", 1)[0]
        if raw_path and raw_path != ":memory:":
            source = Path(raw_path)
            suffix = source.suffix or ".sqlite"
            history_name = f"{source.stem}_history{suffix}"
            return str(source.with_name(history_name))
    return str(_DEFAULT_HISTORY_DB_PATH)


def init_history_store(db_path: str) -> None:
    """Create the checkpoint table if it does not already exist."""
    _ensure_parent_dir(db_path)
    with closing(open_db(Path(db_path))) as conn, conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()


def save_checkpoint(db_path: str, work_item_id: str, history_json: str, round_count: int) -> None:
    """Upsert a checkpoint row for one work item id."""
    _ensure_parent_dir(db_path)
    now = datetime.now(UTC).isoformat()
    with closing(open_db(Path(db_path))) as conn, conn:
        conn.execute(
            """
            INSERT INTO agent_history_checkpoints (
                work_item_id,
                history_json,
                round_count,
                checkpoint_version,
                updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(work_item_id) DO UPDATE SET
                history_json = excluded.history_json,
                round_count = excluded.round_count,
                checkpoint_version = excluded.checkpoint_version,
                updated_at = excluded.updated_at
            """,
            (work_item_id, history_json, round_count, _CHECKPOINT_VERSION, now),
        )
        conn.commit()


def load_checkpoint(db_path: str, work_item_id: str) -> str | None:
    """Load one checkpoint row by work item id.

    Returns ``None`` when the row is missing or when the checkpoint version
    is stale compared to this process.
    """
    _ensure_parent_dir(db_path)
    with closing(open_db(Path(db_path))) as conn, conn:
        row = conn.execute(
            """
            SELECT history_json, checkpoint_version
            FROM agent_history_checkpoints
            WHERE work_item_id = ?
            """,
            (work_item_id,),
        ).fetchone()
    if row is None:
        return None
    checkpoint_version = int(row[1])
    if checkpoint_version != _CHECKPOINT_VERSION:
        return None
    return str(row[0])


def clear_checkpoint(db_path: str, work_item_id: str) -> None:
    """Delete one checkpoint row after successful completion."""
    _ensure_parent_dir(db_path)
    with closing(open_db(Path(db_path))) as conn, conn:
        conn.execute(
            "DELETE FROM agent_history_checkpoints WHERE work_item_id = ?",
            (work_item_id,),
        )
        conn.commit()


def cleanup_stale_checkpoints(db_path: str, max_age_hours: int = 24) -> int:
    """Delete checkpoints older than ``max_age_hours`` and return rows deleted."""
    _ensure_parent_dir(db_path)
    cutoff = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
    with closing(open_db(Path(db_path))) as conn, conn:
        cursor = conn.execute(
            "DELETE FROM agent_history_checkpoints WHERE updated_at < ?",
            (cutoff,),
        )
        conn.commit()
        deleted = cursor.rowcount
    return max(deleted, 0)


def _ensure_parent_dir(db_path: str) -> None:
    """Ensure the SQLite file's parent directory exists."""
    Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
