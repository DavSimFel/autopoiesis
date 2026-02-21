"""REST API routes that wrap internal MCP tool calls for the PWA frontend.

Each endpoint calls the underlying FastMCP tool functions directly (no
JSON-RPC / MCP protocol exposed to the browser) and returns UIEvent-shaped
JSON: ``{ type, data, meta }``.

Auth
----
CF Access terminates authentication before the request reaches FastAPI.  No
additional token validation is performed here.

SSE stream
----------
``GET /api/stream`` uses ``sse_starlette`` (EventSourceResponse) to push
UIEvents to clients.  A lightweight polling loop broadcasts status and
pending-approval summaries so the PWA dashboard stays live.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from autopoiesis.server.mcp_server import (
    approval_decide,
    approval_list,
    dashboard_status,
    mcp,
)

_log = logging.getLogger(__name__)

api_router = APIRouter(prefix="/api", tags=["api"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SSE_POLL_INTERVAL_SECONDS: float = 5.0


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_envelope(raw: str) -> dict[str, Any]:
    """Parse a JSON envelope string returned by an MCP tool function."""
    try:
        return json.loads(raw)  # type: ignore[return-value]
    except json.JSONDecodeError as exc:
        _log.error("Failed to parse MCP tool envelope: %s", exc)
        return {
            "type": "error.parse",
            "data": {"message": "Invalid envelope from tool", "raw": raw},
            "meta": {"timestamp": _utc_now_iso()},
        }


def _error_envelope(
    error_type: str,
    message: str,
    status_code: int = 400,
) -> tuple[dict[str, Any], int]:
    payload: dict[str, Any] = {
        "type": error_type,
        "data": {"message": message},
        "meta": {"timestamp": _utc_now_iso()},
    }
    return payload, status_code


def _tool_result_to_dict(result: Any) -> dict[str, Any]:
    """Convert a FastMCP ``ToolResult`` to a plain dict."""
    # Prefer structured_content when available (typed output schema)
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured  # type: ignore[return-value]

    # Fall back to text content list
    content = getattr(result, "content", None)
    if content is not None:
        texts: list[str] = []
        for item in content:
            text: str | None = getattr(item, "text", None)
            if text is not None:
                texts.append(text)
        if len(texts) == 1:
            # Single text item — try JSON-parsing it (our tool functions return
            # JSON envelope strings via json_envelope())
            try:
                return json.loads(texts[0])  # type: ignore[return-value]
            except (json.JSONDecodeError, ValueError):
                return {"result": texts[0]}
        if texts:
            return {"result": texts}

    # Last resort: model_dump if pydantic model
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        return dump()  # type: ignore[return-value]

    return {"result": str(result)}


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------


@api_router.get("/status")
async def get_status() -> JSONResponse:
    """Return runtime health and pending approval count as a UIEvent."""
    raw = dashboard_status()
    payload = _parse_envelope(raw)
    return JSONResponse(content=payload)


# ---------------------------------------------------------------------------
# GET /api/approvals
# ---------------------------------------------------------------------------


@api_router.get("/approvals")
async def get_approvals() -> JSONResponse:
    """Return pending approval envelopes as a UIEvent."""
    raw = approval_list()
    payload = _parse_envelope(raw)
    return JSONResponse(content=payload)


# ---------------------------------------------------------------------------
# POST /api/actions
# ---------------------------------------------------------------------------


class ActionRequest(BaseModel):
    """Body for POST /api/actions."""

    action: str  # "approve" | "reject" | "send_message"
    approval_id: str | None = None
    reason: str | None = None
    # Generic extra payload forwarded as-is for future actions
    payload: dict[str, Any] | None = None


@api_router.post("/actions")
async def post_action(body: ActionRequest) -> JSONResponse:
    """Route an action to the appropriate internal MCP tool.

    Supported actions
    -----------------
    - ``approve``      — approve a pending approval envelope
    - ``reject``       — reject a pending approval envelope
    - ``send_message`` — placeholder; not yet wired to a tool
    """
    action = body.action

    if action in ("approve", "reject"):
        if not body.approval_id:
            payload, code = _error_envelope(
                "error.missing_field",
                "approval_id is required for approve/reject",
                400,
            )
            return JSONResponse(content=payload, status_code=code)

        approved = action == "approve"
        raw = await approval_decide(
            approval_id=body.approval_id,
            approved=approved,
            reason=body.reason,
        )
        result_payload = _parse_envelope(raw)
        # Map approval_not_found to 404
        if result_payload.get("type") == "error.approval_not_found":
            return JSONResponse(content=result_payload, status_code=404)
        return JSONResponse(content=result_payload)

    if action == "send_message":
        # Attempt to call the MCP tool if registered; otherwise return 501
        if mcp is not None:
            try:
                tool_result = await mcp.call_tool(
                    "send_message",
                    body.payload or {},
                )
                data = _tool_result_to_dict(tool_result)
                envelope: dict[str, Any] = {
                    "type": "action.send_message",
                    "data": data,
                    "meta": {"timestamp": _utc_now_iso()},
                }
                return JSONResponse(content=envelope)
            except Exception as exc:
                _log.warning("send_message tool call failed: %s", exc)
        payload_501, code_501 = _error_envelope(
            "error.not_implemented",
            "send_message action is not yet supported",
            501,
        )
        return JSONResponse(content=payload_501, status_code=code_501)

    payload_400, code_400 = _error_envelope(
        "error.unknown_action",
        f"Unknown action: {action!r}. Valid: approve, reject, send_message",
        400,
    )
    return JSONResponse(content=payload_400, status_code=code_400)


# ---------------------------------------------------------------------------
# GET /api/tools
# ---------------------------------------------------------------------------


@api_router.get("/tools")
async def list_tools() -> JSONResponse:
    """List available MCP tools for the PWA 'More' page."""
    if mcp is None:
        payload, code = _error_envelope(
            "error.mcp_unavailable",
            "MCP server is not available",
            503,
        )
        return JSONResponse(content=payload, status_code=code)

    tools = await mcp.list_tools()
    tool_dicts: list[dict[str, Any]] = []
    for tool in tools:
        mcp_tool = tool.to_mcp_tool()
        tool_dicts.append(mcp_tool.model_dump(exclude_none=True))

    envelope: dict[str, Any] = {
        "type": "tools.list",
        "data": {"count": len(tool_dicts), "tools": tool_dicts},
        "meta": {"timestamp": _utc_now_iso()},
    }
    return JSONResponse(content=envelope)


# ---------------------------------------------------------------------------
# POST /api/tools/{name}
# ---------------------------------------------------------------------------


@api_router.post("/tools/{name}")
async def call_tool(name: str, body: dict[str, Any] | None = None) -> JSONResponse:
    """Call a specific MCP tool by name and return its result as UIEvent JSON."""
    if mcp is None:
        payload, code = _error_envelope(
            "error.mcp_unavailable",
            "MCP server is not available",
            503,
        )
        return JSONResponse(content=payload, status_code=code)

    try:
        result = await mcp.call_tool(name, body or {})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Tool {name!r} not found") from exc
    except Exception as exc:
        _log.error("Tool %r raised: %s", name, exc)
        payload_500, code_500 = _error_envelope(
            "error.tool_failed",
            str(exc),
            500,
        )
        return JSONResponse(content=payload_500, status_code=code_500)

    data = _tool_result_to_dict(result)
    # If data is itself a UIEvent envelope (our own tool functions return JSON
    # envelope strings that _tool_result_to_dict already parsed), pass through
    # as-is.
    if "type" in data and "data" in data and "meta" in data:
        return JSONResponse(content=data)

    envelope: dict[str, Any] = {
        "type": f"tool.result.{name}",
        "data": data,
        "meta": {"tool": name, "timestamp": _utc_now_iso()},
    }
    return JSONResponse(content=envelope)


# ---------------------------------------------------------------------------
# GET /api/stream  (SSE)
# ---------------------------------------------------------------------------


async def _sse_event_generator() -> AsyncGenerator[dict[str, str], None]:
    """Async generator that yields UIEvents as SSE data frames.

    Sends a ``connected`` handshake immediately, then polls ``dashboard_status``
    and ``approval_list`` every :data:`_SSE_POLL_INTERVAL_SECONDS` seconds.
    Terminates when the client disconnects (``asyncio.CancelledError``).
    """
    # --- handshake ---
    handshake: dict[str, Any] = {
        "type": "stream.connected",
        "data": {},
        "meta": {"timestamp": _utc_now_iso()},
    }
    yield {"event": "message", "data": json.dumps(handshake)}

    try:
        while True:
            # status heartbeat
            status_payload = _parse_envelope(dashboard_status())
            yield {
                "event": "message",
                "data": json.dumps(status_payload),
            }

            # pending approvals
            approvals_payload = _parse_envelope(approval_list())
            yield {
                "event": "message",
                "data": json.dumps(approvals_payload),
            }

            await asyncio.sleep(_SSE_POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        _log.debug("SSE client disconnected")
        # EventSourceResponse expects the generator to simply stop
        return


@api_router.get("/stream")
async def sse_stream() -> EventSourceResponse:
    """Server-Sent Events endpoint that pushes UIEvents to the PWA dashboard."""
    return EventSourceResponse(_sse_event_generator())
