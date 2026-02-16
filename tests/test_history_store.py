"""Tests for SQLite-backed history checkpoint persistence."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from history_store import (
    cleanup_stale_checkpoints,
    clear_checkpoint,
    load_checkpoint,
    resolve_history_db_path,
    save_checkpoint,
)


def test_save_and_load_checkpoint_round_trip(history_db: str) -> None:
    save_checkpoint(history_db, "item-1", '{"messages":[]}', 2)
    assert load_checkpoint(history_db, "item-1") == '{"messages":[]}'


def test_load_checkpoint_returns_none_for_unknown_id(history_db: str) -> None:
    assert load_checkpoint(history_db, "missing-item") is None


def test_save_checkpoint_upserts_existing_row(history_db: str) -> None:
    save_checkpoint(history_db, "item-2", '{"messages":["a"]}', 1)
    save_checkpoint(history_db, "item-2", '{"messages":["b"]}', 3)
    assert load_checkpoint(history_db, "item-2") == '{"messages":["b"]}'


def test_clear_checkpoint_removes_entry(history_db: str) -> None:
    save_checkpoint(history_db, "item-3", '{"messages":[]}', 1)
    clear_checkpoint(history_db, "item-3")
    assert load_checkpoint(history_db, "item-3") is None


def test_cleanup_stale_checkpoints_removes_old_rows(history_db: str) -> None:
    save_checkpoint(history_db, "old-item", '{"messages":[]}', 1)
    save_checkpoint(history_db, "new-item", '{"messages":[]}', 1)

    stale_time = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    with sqlite3.connect(history_db) as conn:
        conn.execute(
            "UPDATE agent_history_checkpoints SET updated_at = ? WHERE work_item_id = ?",
            (stale_time, "old-item"),
        )
        conn.commit()

    deleted = cleanup_stale_checkpoints(history_db, max_age_hours=24)
    assert deleted == 1
    assert load_checkpoint(history_db, "old-item") is None
    assert load_checkpoint(history_db, "new-item") == '{"messages":[]}'


def test_load_checkpoint_returns_none_for_stale_checkpoint_version(history_db: str) -> None:
    save_checkpoint(history_db, "item-4", '{"messages":[]}', 1)
    with sqlite3.connect(history_db) as conn:
        conn.execute(
            "UPDATE agent_history_checkpoints SET checkpoint_version = ? WHERE work_item_id = ?",
            (999, "item-4"),
        )
        conn.commit()
    assert load_checkpoint(history_db, "item-4") is None


def test_resolve_history_db_path_handles_sqlite_and_postgres(tmp_path: Path) -> None:
    sqlite_url = f"sqlite:///{tmp_path}/db.sqlite"
    sqlite_path = resolve_history_db_path(sqlite_url)
    postgres_path = resolve_history_db_path("postgresql://user:pass@localhost:5432/app")

    assert Path(sqlite_path) == tmp_path / "db_history.sqlite"
    assert Path(postgres_path).as_posix().endswith("data/history.sqlite")
