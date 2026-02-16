"""Schema and migration helpers for approval envelope storage."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4


def utc_now_epoch() -> int:
    """Return UTC epoch seconds."""
    return int(datetime.now(UTC).timestamp())


def init_schema(conn: sqlite3.Connection) -> None:
    """Create or migrate the approval envelope schema to current shape."""
    if not _table_exists(conn, "approval_envelopes"):
        _create_schema(conn)
        return
    if _schema_is_current(conn):
        return
    _migrate_legacy_schema(conn)


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE approval_envelopes (
            envelope_id TEXT PRIMARY KEY,
            nonce TEXT UNIQUE NOT NULL,
            scope_json TEXT NOT NULL,
            tool_calls_json TEXT NOT NULL,
            plan_hash TEXT NOT NULL,
            key_id TEXT NOT NULL,
            signed_object_json TEXT,
            signature_hex TEXT,
            state TEXT NOT NULL,
            issued_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            consumed_at INTEGER
        )
        """
    )


def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE approval_envelopes RENAME TO approval_envelopes_legacy")
    _create_schema(conn)
    now = utc_now_epoch()
    rows = cast(
        list[sqlite3.Row],
        conn.execute(
            """
        SELECT nonce, scope_json, tool_calls_json, plan_hash, state,
               issued_at, expires_at, consumed_at
        FROM approval_envelopes_legacy
        """
        ).fetchall(),
    )
    for row in rows:
        state = str(row["state"])
        migrated_state = "expired" if state == "pending" else state
        migrated_consumed_at = (
            now
            if state == "pending"
            else int(row["consumed_at"])
            if row["consumed_at"] is not None
            else None
        )
        conn.execute(
            """
            INSERT INTO approval_envelopes (
                envelope_id, nonce, scope_json, tool_calls_json, plan_hash, key_id,
                signed_object_json, signature_hex, state, issued_at, expires_at, consumed_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                str(row["nonce"]),
                str(row["scope_json"]),
                str(row["tool_calls_json"]),
                str(row["plan_hash"]),
                "",
                migrated_state,
                int(row["issued_at"]),
                int(row["expires_at"]),
                migrated_consumed_at,
            ),
        )
    conn.execute("DROP TABLE approval_envelopes_legacy")


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _schema_is_current(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA table_info(approval_envelopes)").fetchall()
    columns = {str(row[1]) for row in rows}
    expected = {
        "envelope_id",
        "nonce",
        "scope_json",
        "tool_calls_json",
        "plan_hash",
        "key_id",
        "signed_object_json",
        "signature_hex",
        "state",
        "issued_at",
        "expires_at",
        "consumed_at",
    }
    return columns == expected
