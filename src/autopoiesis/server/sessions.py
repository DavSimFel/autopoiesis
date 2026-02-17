"""In-memory session store for the server."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import uuid4

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from autopoiesis.server.models import SessionInfo


class SessionStore:
    """Thread-safe in-memory session manager.

    Stores session metadata and serialized message history.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._history: dict[str, str | None] = {}
        self._last_active: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def _touch(self, session_id: str) -> None:
        """Update the last-active timestamp for a session (caller holds lock)."""
        self._last_active[session_id] = datetime.now(UTC)

    def create(self, session_id: str | None = None) -> SessionInfo:
        """Create a new session, returning its metadata."""
        sid = session_id or uuid4().hex
        info = SessionInfo(id=sid, created_at=datetime.now(UTC), message_count=0)
        with self._lock:
            self._sessions[sid] = info
            self._history[sid] = None
            self._touch(sid)
        return info

    def get(self, session_id: str) -> SessionInfo | None:
        """Return session info or None if not found."""
        with self._lock:
            return self._sessions.get(session_id)

    def list_all(self) -> list[SessionInfo]:
        """Return all sessions."""
        with self._lock:
            return list(self._sessions.values())

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        with self._lock:
            existed = session_id in self._sessions
            self._sessions.pop(session_id, None)
            self._history.pop(session_id, None)
            self._last_active.pop(session_id, None)
            return existed

    def get_history_json(self, session_id: str) -> str | None:
        """Return raw history JSON for a session."""
        with self._lock:
            return self._history.get(session_id)

    def set_history_json(self, session_id: str, history_json: str | None) -> None:
        """Update stored history JSON and message count."""
        with self._lock:
            self._history[session_id] = history_json
            self._touch(session_id)
            info = self._sessions.get(session_id)
            if info is not None and history_json is not None:
                messages = ModelMessagesTypeAdapter.validate_json(history_json)
                info.message_count = len(messages)

    def get_messages(self, session_id: str) -> list[ModelMessage]:
        """Parse and return message history for a session."""
        history_json = self.get_history_json(session_id)
        if not history_json:
            return []
        return list(ModelMessagesTypeAdapter.validate_json(history_json))

    def exists(self, session_id: str) -> bool:
        """Check if a session exists."""
        with self._lock:
            return session_id in self._sessions

    def backdate_last_active(self, session_id: str, timestamp: datetime) -> None:
        """Set last-active to *timestamp* (for testing)."""
        with self._lock:
            self._last_active[session_id] = timestamp

    def remove_stale(
        self,
        ttl_seconds: int,
        active_sessions: set[str],
    ) -> list[str]:
        """Remove sessions that have no active WebSocket connections and
        haven't been touched within *ttl_seconds*.

        Returns the list of removed session IDs.
        """
        now = datetime.now(UTC)
        removed: list[str] = []
        with self._lock:
            for sid in list(self._sessions):
                if sid in active_sessions:
                    continue
                last = self._last_active.get(sid, self._sessions[sid].created_at)
                if (now - last).total_seconds() > ttl_seconds:
                    self._sessions.pop(sid, None)
                    self._history.pop(sid, None)
                    self._last_active.pop(sid, None)
                    removed.append(sid)
        return removed
