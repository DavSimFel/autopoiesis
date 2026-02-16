"""In-memory session store for the server."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import uuid4

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from server.models import SessionInfo


class SessionStore:
    """Thread-safe in-memory session manager.

    Stores session metadata and serialized message history.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._history: dict[str, str | None] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str | None = None) -> SessionInfo:
        """Create a new session, returning its metadata."""
        sid = session_id or uuid4().hex
        info = SessionInfo(id=sid, created_at=datetime.now(UTC), message_count=0)
        with self._lock:
            self._sessions[sid] = info
            self._history[sid] = None
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
            return existed

    def get_history_json(self, session_id: str) -> str | None:
        """Return raw history JSON for a session."""
        with self._lock:
            return self._history.get(session_id)

    def set_history_json(self, session_id: str, history_json: str | None) -> None:
        """Update stored history JSON and message count."""
        with self._lock:
            self._history[session_id] = history_json
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
