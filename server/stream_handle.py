"""WebSocket stream handle implementing the streaming protocol."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from server.models import WSOutgoing

if TYPE_CHECKING:
    from server.connections import ConnectionManager

_log = logging.getLogger(__name__)


class WebSocketStreamHandle:
    """Stream handle that sends agent output over WebSocket.

    Implements the same interface as RichStreamHandle but broadcasts
    over WebSocket to all connected clients in a session.
    """

    def __init__(
        self,
        session_id: str,
        manager: ConnectionManager,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._session_id = session_id
        self._manager = manager
        self._loop = loop
        self._closed = False

    def _send(self, message: WSOutgoing) -> None:
        """Schedule a broadcast on the event loop (thread-safe)."""
        if self._closed:
            return
        asyncio.run_coroutine_threadsafe(
            self._manager.broadcast(self._session_id, message),
            self._loop,
        )

    def write(self, chunk: str) -> None:
        """Send a token chunk to all connected clients."""
        self._send(WSOutgoing(op="token", data={"content": chunk}))

    def close(self) -> None:
        """Signal streaming complete."""
        if self._closed:
            return
        self._closed = True
        self._send(WSOutgoing(op="done", data={}))

    def start_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        details: str | None = None,
    ) -> None:
        """Notify clients that a tool call has started."""
        self._send(
            WSOutgoing(
                op="tool_call",
                data={
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "details": details,
                },
            )
        )

    def finish_tool_call(
        self,
        tool_call_id: str,
        status: str,
        details: str | None = None,
    ) -> None:
        """Notify clients that a tool call finished."""
        self._send(
            WSOutgoing(
                op="tool_result",
                data={
                    "tool_call_id": tool_call_id,
                    "status": status,
                    "details": details,
                },
            )
        )

    def start_thinking(self) -> None:
        """Signal reasoning started."""
        self._send(WSOutgoing(op="thinking_start", data={}))

    def update_thinking(self, chunk: str) -> None:
        """Send thinking content."""
        self._send(WSOutgoing(op="thinking", data={"content": chunk}))

    def finish_thinking(self) -> None:
        """Signal reasoning complete."""
        self._send(WSOutgoing(op="thinking_done", data={}))

    def pause_display(self) -> None:
        """No-op for WebSocket (no terminal to pause)."""

    def resume_display(self) -> None:
        """No-op for WebSocket."""
