"""Tests for SQLite-backed history checkpoint persistence."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from history_store import (
    cleanup_stale_checkpoints,
    clear_checkpoint,
    init_history_store,
    load_checkpoint,
    resolve_history_db_path,
    save_checkpoint,
)


def test_save_and_load_checkpoint_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "history.sqlite"
    init_history_store(str(db_path))

    save_checkpoint(str(db_path), "item-1", '{"messages":[]}', 2)

    assert load_checkpoint(str(db_path), "item-1") == ('{"messages":[]}', 2)


def test_load_checkpoint_returns_none_for_unknown_id(tmp_path: Path) -> None:
    db_path = tmp_path / "history.sqlite"
    init_history_store(str(db_path))

    assert load_checkpoint(str(db_path), "missing-item") is None


def test_save_checkpoint_upserts_existing_row(tmp_path: Path) -> None:
    db_path = tmp_path / "history.sqlite"
    init_history_store(str(db_path))

    save_checkpoint(str(db_path), "item-2", '{"messages":["a"]}', 1)
    save_checkpoint(str(db_path), "item-2", '{"messages":["b"]}', 3)

    assert load_checkpoint(str(db_path), "item-2") == ('{"messages":["b"]}', 3)


def test_clear_checkpoint_removes_entry(tmp_path: Path) -> None:
    db_path = tmp_path / "history.sqlite"
    init_history_store(str(db_path))
    save_checkpoint(str(db_path), "item-3", '{"messages":[]}', 1)

    clear_checkpoint(str(db_path), "item-3")

    assert load_checkpoint(str(db_path), "item-3") is None


def test_cleanup_stale_checkpoints_removes_old_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "history.sqlite"
    init_history_store(str(db_path))
    save_checkpoint(str(db_path), "old-item", '{"messages":[]}', 1)
    save_checkpoint(str(db_path), "new-item", '{"messages":[]}', 1)

    stale_time = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE agent_history_checkpoints
            SET updated_at = ?
            WHERE work_item_id = ?
            """,
            (stale_time, "old-item"),
        )
        conn.commit()

    deleted = cleanup_stale_checkpoints(str(db_path), max_age_hours=24)

    assert deleted == 1
    assert load_checkpoint(str(db_path), "old-item") is None
    assert load_checkpoint(str(db_path), "new-item") == ('{"messages":[]}', 1)


def test_resolve_history_db_path_handles_sqlite_and_postgres(tmp_path: Path) -> None:
    sqlite_url = f"sqlite:///{tmp_path}/db.sqlite"
    sqlite_path = resolve_history_db_path(sqlite_url)
    postgres_path = resolve_history_db_path("postgresql://user:pass@localhost:5432/app")

    assert Path(sqlite_path) == tmp_path / "db_history.sqlite"
    assert Path(postgres_path).as_posix().endswith("data/history.sqlite")
