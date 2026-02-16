"""Subscription registry for reactive context injection.

Subscriptions are references to files or memory queries that get
automatically materialized (resolved to current content) before each
agent turn.  Content is injected into the conversation so the agent
always sees the freshest version of subscribed resources.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from db import open_db

logger = logging.getLogger(__name__)

MAX_SUBSCRIPTIONS = 10
MAX_CONTENT_CHARS = 2000
EXPIRY_SECONDS = 86400  # 24 h

SubscriptionKind = Literal["file", "lines", "memory"]

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    line_range_start INTEGER,
    line_range_end INTEGER,
    pattern TEXT,
    content_hash TEXT NOT NULL DEFAULT '',
    sort_key INTEGER NOT NULL,
    session_id TEXT,
    created_at REAL NOT NULL,
    UNIQUE(session_id, target, kind)
);
"""


@dataclass(frozen=True)
class Subscription:
    """A reference to a resource that gets materialized each turn."""

    id: str
    kind: SubscriptionKind
    target: str
    line_range: tuple[int, int] | None
    pattern: str | None
    content_hash: str
    sort_key: int
    session_id: str | None
    created_at: float


@dataclass(frozen=True)
class MaterializedContent:
    """Resolved content from a subscription."""

    subscription: Subscription
    header: str
    content: str
    content_hash: str


class SubscriptionRegistry:
    """Manages active subscriptions backed by SQLite."""

    def __init__(self, db_path: str, session_id: str | None = None) -> None:
        self._db_path = db_path
        self._session_id = session_id
        self._init_db()

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(open_db(Path(self._db_path))) as conn, conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return open_db(Path(self._db_path))

    def add(
        self,
        kind: SubscriptionKind,
        target: str,
        line_range: tuple[int, int] | None = None,
        pattern: str | None = None,
    ) -> Subscription:
        """Add a subscription.  Raises ValueError when limit exceeded."""
        with closing(self._connect()) as conn, conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE session_id IS ?",
                (self._session_id,),
            ).fetchone()[0]
            if count >= MAX_SUBSCRIPTIONS:
                msg = f"Subscription limit ({MAX_SUBSCRIPTIONS}) reached."
                raise ValueError(msg)
            next_sort = count + 1
            sub = Subscription(
                id=uuid4().hex[:12],
                kind=kind,
                target=target,
                line_range=line_range,
                pattern=pattern,
                content_hash="",
                sort_key=next_sort,
                session_id=self._session_id,
                created_at=time.time(),
            )
            conn.execute(
                """INSERT OR REPLACE INTO subscriptions
                   (id,kind,target,line_range_start,line_range_end,
                    pattern,content_hash,sort_key,session_id,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    sub.id,
                    sub.kind,
                    sub.target,
                    sub.line_range[0] if sub.line_range else None,
                    sub.line_range[1] if sub.line_range else None,
                    sub.pattern,
                    sub.content_hash,
                    sub.sort_key,
                    sub.session_id,
                    sub.created_at,
                ),
            )
            conn.commit()
        return sub

    def remove(self, subscription_id: str) -> bool:
        """Remove a subscription by id.  Returns True if deleted."""
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "DELETE FROM subscriptions WHERE id=? AND session_id IS ?",
                (subscription_id, self._session_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def remove_all(self) -> int:
        """Remove all subscriptions for the current session."""
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "DELETE FROM subscriptions WHERE session_id IS ?",
                (self._session_id,),
            )
            conn.commit()
            return cur.rowcount

    def get_active(self) -> list[Subscription]:
        """Return all active (non-expired) subscriptions, sorted."""
        cutoff = time.time() - EXPIRY_SECONDS
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                """SELECT * FROM subscriptions
                   WHERE session_id IS ? AND created_at > ?
                   ORDER BY sort_key""",
                (self._session_id, cutoff),
            ).fetchall()
        return [_row_to_subscription(r) for r in rows]

    def update_hash(self, subscription_id: str, content_hash: str) -> None:
        """Update the content hash after materialization."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE subscriptions SET content_hash=? WHERE id=?",
                (content_hash, subscription_id),
            )
            conn.commit()

    def expire_stale(self) -> int:
        """Delete subscriptions older than EXPIRY_SECONDS."""
        cutoff = time.time() - EXPIRY_SECONDS
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "DELETE FROM subscriptions WHERE created_at <= ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount


def _row_to_subscription(row: sqlite3.Row) -> Subscription:
    start = row["line_range_start"]
    end = row["line_range_end"]
    lr = (start, end) if start is not None and end is not None else None
    return Subscription(
        id=row["id"],
        kind=row["kind"],
        target=row["target"],
        line_range=lr,
        pattern=row["pattern"],
        content_hash=row["content_hash"],
        sort_key=row["sort_key"],
        session_id=row["session_id"],
        created_at=row["created_at"],
    )


def content_hash(text: str) -> str:
    """Return a short SHA-256 digest of *text*."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def truncate_content(text: str, limit: int = MAX_CONTENT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (truncated at {limit} chars)"
