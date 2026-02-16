"""API key authentication for the server."""

from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request, WebSocket, status


def get_api_key() -> str | None:
    """Return configured API key, or None if auth is disabled."""
    return os.getenv("AUTOPOIESIS_API_KEY")


def verify_api_key(request: Request) -> None:
    """Verify X-API-Key header against configured key. No-op if key not set."""
    expected = get_api_key()
    if expected is None:
        return
    provided = request.headers.get("X-API-Key", "")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


async def verify_ws_api_key(websocket: WebSocket) -> bool:
    """Verify API key for WebSocket connections via X-API-Key header only.

    Query-parameter auth is intentionally not supported to avoid leaking
    credentials in server logs and Referer headers.  Browser clients should
    authenticate via a token in the first WebSocket message or use a
    one-time upgrade token (future work).

    Returns True if valid.
    """
    expected = get_api_key()
    if expected is None:
        return True
    provided = websocket.headers.get("X-API-Key", "")
    return secrets.compare_digest(provided, expected) if provided else False
