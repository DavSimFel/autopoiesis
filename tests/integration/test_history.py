"""Section 8: History & Recovery integration tests."""

from __future__ import annotations

import json

from autopoiesis.store.history import (
    cleanup_stale_checkpoints,
    clear_checkpoint,
    load_checkpoint,
    save_checkpoint,
)


class TestCheckpointSavesAfterTurn:
    """8.1 — Checkpoint saves after turn."""

    def test_save_and_load_checkpoint(self, history_db: str) -> None:
        history_json = json.dumps([{"role": "user", "content": "hello"}])
        save_checkpoint(history_db, "work-item-001", history_json, round_count=1)

        loaded = load_checkpoint(history_db, "work-item-001")
        assert loaded is not None
        assert json.loads(loaded) == [{"role": "user", "content": "hello"}]


class TestRecoveryLoadsFromCheckpoint:
    """8.2 — Recovery loads from checkpoint."""

    def test_checkpoint_round_trip(self, history_db: str) -> None:
        messages = [
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "I'll fix it"},
        ]
        history_json = json.dumps(messages)
        save_checkpoint(history_db, "work-item-002", history_json, round_count=2)

        loaded = load_checkpoint(history_db, "work-item-002")
        assert loaded is not None
        recovered = json.loads(loaded)
        assert len(recovered) == 2
        assert recovered[0]["content"] == "fix the bug"

    def test_missing_checkpoint_returns_none(self, history_db: str) -> None:
        assert load_checkpoint(history_db, "nonexistent") is None

    def test_clear_checkpoint(self, history_db: str) -> None:
        save_checkpoint(history_db, "work-item-003", "[]", round_count=0)
        clear_checkpoint(history_db, "work-item-003")
        assert load_checkpoint(history_db, "work-item-003") is None


class TestStaleCheckpointsCleanup:
    """8.3 — Stale checkpoints cleaned."""

    def test_old_checkpoints_removed(self, history_db: str) -> None:
        save_checkpoint(history_db, "old-item", "[]", round_count=0)

        # Manually backdate the checkpoint
        from contextlib import closing
        from pathlib import Path

        from autopoiesis.db import open_db

        with closing(open_db(Path(history_db))) as conn, conn:
            conn.execute("UPDATE agent_history_checkpoints SET updated_at = '2020-01-01T00:00:00'")
            conn.commit()

        deleted = cleanup_stale_checkpoints(history_db, max_age_hours=1)
        assert deleted >= 1
        assert load_checkpoint(history_db, "old-item") is None
