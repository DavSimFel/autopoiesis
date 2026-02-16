"""WebSocket connection manager for multi-device session support."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

from server.models import WSOutgoing

_log = logging.getLogger(__name__)


class ConnectionManager:
    """Track WebSocket connections per session and broadcast events."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection for a session."""
        await websocket.accept()
        async with self._lock:
            self._connections[session_id].append(websocket)
        count = self.client_count(session_id)
        _log.info("Client connected to session %s (%d total)", session_id, count)

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from a session."""
        async with self._lock:
            clients = self._connections.get(session_id, [])
            if websocket in clients:
                clients.remove(websocket)
            if not clients:
                self._connections.pop(session_id, None)
        _log.info("Client disconnected from session %s", session_id)

    async def broadcast(self, session_id: str, message: WSOutgoing) -> None:
        """Send a message to all connected clients in a session."""
        async with self._lock:
            clients = list(self._connections.get(session_id, []))
        payload = message.model_dump_json()
        disconnected: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.append(ws)
        if disconnected:
            async with self._lock:
                session_clients = self._connections.get(session_id, [])
                for ws in disconnected:
                    if ws in session_clients:
                        session_clients.remove(ws)

    def client_count(self, session_id: str) -> int:
        """Return number of connected clients for a session."""
        return len(self._connections.get(session_id, []))

    def active_sessions(self) -> list[str]:
        """Return list of session IDs with active connections."""
        return list(self._connections.keys())
