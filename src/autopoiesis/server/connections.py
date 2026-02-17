"""WebSocket connection manager for multi-device session support."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

from autopoiesis.server.models import WSOutgoing

_log = logging.getLogger(__name__)


async def _send_one(session_id: str, ws: WebSocket, payload: str) -> WebSocket | None:
    """Try sending *payload* to a single client; return the socket on failure."""
    try:
        await ws.send_text(payload)
    except Exception:
        _log.warning("Failed to send to client in session %s, marking as dead", session_id)
        return ws
    return None


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
        """Send a message to all connected clients in a session concurrently."""
        async with self._lock:
            clients = list(self._connections.get(session_id, []))
        if not clients:
            return

        payload = message.model_dump_json()
        results = await asyncio.gather(
            *[_send_one(session_id, ws, payload) for ws in clients],
            return_exceptions=True,
        )

        disconnected = [r for r in results if isinstance(r, WebSocket)]
        for r in results:
            if isinstance(r, BaseException):
                _log.error("Unexpected error during broadcast: %s", r)

        if disconnected:
            await self._remove_dead(session_id, disconnected)

    async def _remove_dead(self, session_id: str, dead: list[WebSocket]) -> None:
        """Remove dead WebSocket connections from a session."""
        async with self._lock:
            session_clients = self._connections.get(session_id, [])
            for ws in dead:
                if ws in session_clients:
                    session_clients.remove(ws)
            if not session_clients:
                self._connections.pop(session_id, None)

    def client_count(self, session_id: str) -> int:
        """Return number of connected clients for a session."""
        return len(self._connections.get(session_id, []))

    def active_sessions(self) -> list[str]:
        """Return list of session IDs with active connections."""
        return list(self._connections.keys())
