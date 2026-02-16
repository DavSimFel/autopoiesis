"""Pydantic models for server API requests, responses, and WebSocket messages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# --- REST models ---


class ChatRequest(BaseModel):
    """POST /api/chat request body."""

    content: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    """POST /api/chat response body."""

    session_id: str
    content: str


class SessionInfo(BaseModel):
    """Session metadata returned by list/create endpoints."""

    id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    message_count: int = 0


class SessionHistory(BaseModel):
    """GET /api/sessions/{id}/history response."""

    session_id: str
    messages: list[dict[str, Any]]


class HealthResponse(BaseModel):
    """GET /api/health response."""

    status: str = "ok"
    version: str = "0.1.0"


# --- WebSocket models ---


class WSIncoming(BaseModel):
    """Incoming WebSocket message from client."""

    op: str
    data: dict[str, Any] = Field(default_factory=dict)


class WSOutgoing(BaseModel):
    """Outgoing WebSocket message to client."""

    op: str
    data: dict[str, Any] = Field(default_factory=dict)
