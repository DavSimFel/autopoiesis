"""FastAPI application with REST and WebSocket endpoints."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from server.auth import verify_api_key, verify_ws_api_key
from server.connections import ConnectionManager
from server.models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SessionHistory,
    SessionInfo,
    WSIncoming,
    WSOutgoing,
)
from server.sessions import SessionStore

_log = logging.getLogger(__name__)

_manager = ConnectionManager()
_sessions = SessionStore()


def get_connection_manager() -> ConnectionManager:
    """Return the global connection manager."""
    return _manager


def set_connection_manager(manager: ConnectionManager) -> None:
    """Replace the global connection manager."""
    global _manager
    _manager = manager


def get_session_store() -> SessionStore:
    """Return the global session store."""
    return _sessions


def set_session_store(store: SessionStore) -> None:
    """Replace the global session store."""
    global _sessions
    _sessions = store


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — startup/shutdown hooks."""
    _log.info("Autopoiesis server starting")
    yield
    _log.info("Autopoiesis server shutting down")


app = FastAPI(
    title="Autopoiesis",
    version="0.1.0",
    lifespan=lifespan,
)


# --- Health ---


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse()


# --- Sessions CRUD ---


@app.get(
    "/api/sessions",
    response_model=list[SessionInfo],
    dependencies=[Depends(verify_api_key)],
)
def list_sessions() -> list[SessionInfo]:
    """List all sessions."""
    return _sessions.list_all()


@app.post(
    "/api/sessions",
    response_model=SessionInfo,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
)
def create_session() -> SessionInfo:
    """Create a new chat session."""
    return _sessions.create()


@app.get(
    "/api/sessions/{session_id}/history",
    response_model=SessionHistory,
    dependencies=[Depends(verify_api_key)],
)
def get_session_history(session_id: str) -> SessionHistory:
    """Get conversation history for a session."""
    if not _sessions.exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    messages = _sessions.get_messages(session_id)
    return SessionHistory(
        session_id=session_id,
        messages=_serialize_messages_for_api(messages),
    )


@app.delete(
    "/api/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_api_key)],
)
def delete_session(session_id: str) -> None:
    """Delete a session."""
    if not _sessions.delete(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


# --- Chat ---


@app.post(
    "/api/chat",
    response_model=ChatResponse,
    dependencies=[Depends(verify_api_key)],
)
async def chat(request: ChatRequest) -> ChatResponse:
    """Submit a message and get a non-streaming response."""
    session_id = request.session_id or uuid4().hex
    if not _sessions.exists(session_id):
        _sessions.create(session_id)

    try:
        from agent.runtime import get_runtime
        from agent.worker import enqueue_and_wait
        from display.streaming import register_stream
        from models import WorkItem, WorkItemInput, WorkItemPriority, WorkItemType
        from server.stream_handle import WebSocketStreamHandle

        get_runtime()  # Verify runtime is initialized
        history_json = _sessions.get_history_json(session_id)

        loop = asyncio.get_running_loop()
        ws_handle = WebSocketStreamHandle(session_id, _manager, loop)
        item = WorkItem(
            type=WorkItemType.CHAT,
            priority=WorkItemPriority.NORMAL,
            input=WorkItemInput(
                prompt=request.content,
                message_history_json=history_json,
            ),
        )
        register_stream(item.id, ws_handle)
        output = await asyncio.to_thread(enqueue_and_wait, item)
        _sessions.set_history_json(session_id, output.message_history_json)
        return ChatResponse(
            session_id=session_id,
            content=output.text or "",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --- WebSocket ---


@app.websocket("/api/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Bidirectional WebSocket for streaming chat."""
    if not await verify_ws_api_key(websocket):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    if not _sessions.exists(session_id):
        _sessions.create(session_id)

    await _manager.connect(session_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = WSIncoming.model_validate_json(raw)
            except Exception:
                err = WSOutgoing(op="error", data={"message": "Invalid message format"})
                await websocket.send_text(err.model_dump_json())
                continue

            if msg.op == "message":
                await _handle_message(session_id, msg.data, websocket)
            elif msg.op == "approve":
                await _handle_approve(session_id, msg.data, websocket)
            else:
                err = WSOutgoing(op="error", data={"message": f"Unknown op: {msg.op}"})
                await websocket.send_text(err.model_dump_json())
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _log.exception("WebSocket error for session %s", session_id)
        with contextlib.suppress(Exception):
            err = WSOutgoing(op="error", data={"message": str(exc)})
            await websocket.send_text(err.model_dump_json())
    finally:
        await _manager.disconnect(session_id, websocket)


async def _handle_message(
    session_id: str,
    data: dict[str, Any],
    websocket: WebSocket,
) -> None:
    """Process an incoming chat message via the agent."""
    content = data.get("content", "")
    if not content:
        await websocket.send_text(
            WSOutgoing(op="error", data={"message": "Empty message"}).model_dump_json()
        )
        return

    try:
        from agent.runtime import get_runtime
        from agent.worker import enqueue_and_wait
        from display.streaming import register_stream
        from models import WorkItem, WorkItemInput, WorkItemPriority, WorkItemType
        from server.stream_handle import WebSocketStreamHandle

        get_runtime()  # Verify runtime is initialized
        history_json = _sessions.get_history_json(session_id)
        loop = asyncio.get_running_loop()
        ws_handle = WebSocketStreamHandle(session_id, _manager, loop)

        item = WorkItem(
            type=WorkItemType.CHAT,
            priority=WorkItemPriority.NORMAL,
            input=WorkItemInput(
                prompt=content,
                message_history_json=history_json,
            ),
        )
        register_stream(item.id, ws_handle)
        output = await asyncio.to_thread(enqueue_and_wait, item)
        _sessions.set_history_json(session_id, output.message_history_json)

        if output.deferred_tool_requests_json:
            payload = json.loads(output.deferred_tool_requests_json)
            await _manager.broadcast(
                session_id,
                WSOutgoing(
                    op="approval_request",
                    data={
                        "request_id": payload.get("nonce", ""),
                        "requests": payload.get("requests", []),
                    },
                ),
            )
        elif output.text:
            # Final text already streamed via tokens; send done
            await _manager.broadcast(
                session_id,
                WSOutgoing(op="done", data={"content": output.text}),
            )
    except RuntimeError as exc:
        await _manager.broadcast(
            session_id,
            WSOutgoing(op="error", data={"message": str(exc)}),
        )


async def _handle_approve(
    session_id: str,
    data: dict[str, Any],
    websocket: WebSocket,
) -> None:
    """Handle an approval response from the client."""
    # Approval flow placeholder — requires wiring to approval store
    request_id = data.get("request_id", "")
    approved = data.get("approved", False)
    _log.info(
        "Approval for session %s: request=%s approved=%s",
        session_id,
        request_id,
        approved,
    )
    await _manager.broadcast(
        session_id,
        WSOutgoing(
            op="approval_ack",
            data={"request_id": request_id, "approved": approved},
        ),
    )


def _serialize_messages_for_api(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Convert ModelMessages to JSON-serializable dicts for the API."""
    raw = ModelMessagesTypeAdapter.dump_json(messages)
    result: list[dict[str, Any]] = json.loads(raw)
    return result
