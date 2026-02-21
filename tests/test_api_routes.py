"""Tests for the REST API routes that wrap internal MCP tool calls.

These tests use FastAPI's ``TestClient`` (synchronous httpx) and monkeypatching
to isolate the API layer from the real runtime and MCP server.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import autopoiesis.server.api_routes as api_routes_module
from autopoiesis.server.api_routes import api_router
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

_FIXED_TS = "2024-01-01T00:00:00+00:00"


def _envelope(type_: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": type_,
        "data": data,
        "meta": {"tool": type_, "timestamp": _FIXED_TS},
    }


def _raw(type_: str, data: dict[str, Any]) -> str:
    return json.dumps(_envelope(type_, data))


@pytest.fixture()
def client() -> TestClient:
    """Build a minimal FastAPI app with only the api_router attached."""
    app = FastAPI()
    app.include_router(api_router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------


def test_get_status_returns_ui_event(monkeypatch: Any, client: TestClient) -> None:
    raw = _raw("dashboard.status", {"initialized": True, "pending_approvals_count": 0})
    monkeypatch.setattr(api_routes_module, "dashboard_status", lambda: raw)

    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "dashboard.status"
    assert body["data"]["initialized"] is True


def test_get_status_propagates_error_envelope(monkeypatch: Any, client: TestClient) -> None:
    raw = _raw("error.runtime_uninitialized", {"message": "no runtime"})
    monkeypatch.setattr(api_routes_module, "dashboard_status", lambda: raw)

    resp = client.get("/api/status")
    assert resp.status_code == 200  # still 200 — error lives inside the envelope
    body = resp.json()
    assert body["type"] == "error.runtime_uninitialized"


# ---------------------------------------------------------------------------
# GET /api/approvals
# ---------------------------------------------------------------------------


def test_get_approvals_returns_list(monkeypatch: Any, client: TestClient) -> None:
    raw = _raw("approval.list", {"count": 2, "items": [{"id": "a"}, {"id": "b"}]})
    monkeypatch.setattr(api_routes_module, "approval_list", lambda: raw)

    resp = client.get("/api/approvals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "approval.list"
    assert body["data"]["count"] == 2
    assert len(body["data"]["items"]) == 2


def test_get_approvals_empty(monkeypatch: Any, client: TestClient) -> None:
    raw = _raw("approval.list", {"count": 0, "items": []})
    monkeypatch.setattr(api_routes_module, "approval_list", lambda: raw)

    resp = client.get("/api/approvals")
    assert resp.status_code == 200
    assert resp.json()["data"]["count"] == 0


# ---------------------------------------------------------------------------
# POST /api/actions  — approve
# ---------------------------------------------------------------------------


def test_action_approve_calls_approval_decide(monkeypatch: Any, client: TestClient) -> None:
    decision_raw = _raw(
        "approval.decision",
        {"id": "env-1", "state": "consumed", "approved": True},
    )

    async def _fake_decide(
        approval_id: str, approved: bool, reason: str | None = None
    ) -> str:
        assert approval_id == "env-1"
        assert approved is True
        return decision_raw

    monkeypatch.setattr(api_routes_module, "approval_decide", _fake_decide)

    resp = client.post(
        "/api/actions",
        json={"action": "approve", "approval_id": "env-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "approval.decision"
    assert body["data"]["state"] == "consumed"


def test_action_reject_calls_approval_decide(monkeypatch: Any, client: TestClient) -> None:
    decision_raw = _raw(
        "approval.decision",
        {"id": "env-2", "state": "expired", "approved": False},
    )

    async def _fake_decide(
        approval_id: str, approved: bool, reason: str | None = None
    ) -> str:
        assert approved is False
        assert reason == "not safe"
        return decision_raw

    monkeypatch.setattr(api_routes_module, "approval_decide", _fake_decide)

    resp = client.post(
        "/api/actions",
        json={"action": "reject", "approval_id": "env-2", "reason": "not safe"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["approved"] is False


def test_action_approve_missing_id_returns_400(monkeypatch: Any, client: TestClient) -> None:
    resp = client.post("/api/actions", json={"action": "approve"})
    assert resp.status_code == 400
    assert resp.json()["type"] == "error.missing_field"


def test_action_approve_not_found_returns_404(monkeypatch: Any, client: TestClient) -> None:
    not_found_raw = _raw("error.approval_not_found", {"approval_id": "nope"})

    async def _fake_decide(
        approval_id: str, approved: bool, reason: str | None = None
    ) -> str:
        return not_found_raw

    monkeypatch.setattr(api_routes_module, "approval_decide", _fake_decide)

    resp = client.post(
        "/api/actions",
        json={"action": "approve", "approval_id": "nope"},
    )
    assert resp.status_code == 404
    assert resp.json()["type"] == "error.approval_not_found"


def test_action_unknown_returns_400(client: TestClient) -> None:
    resp = client.post("/api/actions", json={"action": "do_something_weird"})
    assert resp.status_code == 400
    assert resp.json()["type"] == "error.unknown_action"


def test_action_send_message_without_mcp_returns_501(
    monkeypatch: Any, client: TestClient
) -> None:
    monkeypatch.setattr(api_routes_module, "mcp", None)
    resp = client.post("/api/actions", json={"action": "send_message", "payload": {}})
    assert resp.status_code == 501
    assert resp.json()["type"] == "error.not_implemented"


# ---------------------------------------------------------------------------
# GET /api/tools
# ---------------------------------------------------------------------------


def _make_fake_mcp(tools_list: list[dict[str, Any]] | None = None) -> MagicMock:
    """Build a mock that quacks like a FastMCP instance."""
    fake = MagicMock()

    tools_list = tools_list or []

    async def _list_tools() -> list[Any]:
        result: list[Any] = []
        for td in tools_list:
            tool = MagicMock()
            mcp_tool = MagicMock()
            mcp_tool.model_dump.return_value = td
            tool.to_mcp_tool.return_value = mcp_tool
            result.append(tool)
        return result

    fake.list_tools = _list_tools
    return fake


def test_get_tools_lists_tools(monkeypatch: Any, client: TestClient) -> None:
    fake_mcp = _make_fake_mcp(
        [
            {"name": "dashboard.status", "description": "Health"},
            {"name": "approval.list", "description": "Approvals"},
        ]
    )
    monkeypatch.setattr(api_routes_module, "mcp", fake_mcp)

    resp = client.get("/api/tools")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "tools.list"
    assert body["data"]["count"] == 2
    names = [t["name"] for t in body["data"]["tools"]]
    assert "dashboard.status" in names


def test_get_tools_mcp_unavailable_returns_503(
    monkeypatch: Any, client: TestClient
) -> None:
    monkeypatch.setattr(api_routes_module, "mcp", None)
    resp = client.get("/api/tools")
    assert resp.status_code == 503
    assert resp.json()["type"] == "error.mcp_unavailable"


# ---------------------------------------------------------------------------
# POST /api/tools/{name}
# ---------------------------------------------------------------------------


def _make_tool_result(text: str) -> MagicMock:
    """Minimal ToolResult-like mock with text content."""
    content_item = MagicMock()
    content_item.text = text
    result = MagicMock()
    result.structured_content = None
    result.content = [content_item]
    return result


def test_call_tool_returns_result(monkeypatch: Any, client: TestClient) -> None:
    fake_result = _make_tool_result("pong")
    fake_mcp = MagicMock()

    async def _call_tool(name: str, args: dict[str, Any]) -> Any:
        return fake_result

    fake_mcp.call_tool = _call_tool
    monkeypatch.setattr(api_routes_module, "mcp", fake_mcp)

    resp = client.post("/api/tools/ping", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "tool.result.ping"
    assert body["data"] == {"result": "pong"}


def test_call_tool_returns_pass_through_for_envelope_text(
    monkeypatch: Any, client: TestClient
) -> None:
    """If the tool returns a JSON UIEvent envelope as text, pass it through."""
    inner_envelope = json.dumps(
        {
            "type": "dashboard.status",
            "data": {"initialized": True},
            "meta": {"tool": "dashboard.status", "timestamp": _FIXED_TS},
        }
    )
    fake_result = _make_tool_result(inner_envelope)
    fake_mcp = MagicMock()

    async def _call_tool(name: str, args: dict[str, Any]) -> Any:
        return fake_result

    fake_mcp.call_tool = _call_tool
    monkeypatch.setattr(api_routes_module, "mcp", fake_mcp)

    resp = client.post("/api/tools/dashboard.status", json={})
    assert resp.status_code == 200
    body = resp.json()
    # Should be the inner envelope, not wrapped again
    assert body["type"] == "dashboard.status"


def test_call_tool_not_found_returns_404(monkeypatch: Any, client: TestClient) -> None:
    fake_mcp = MagicMock()

    async def _call_tool(name: str, args: dict[str, Any]) -> Any:
        raise KeyError(name)

    fake_mcp.call_tool = _call_tool
    monkeypatch.setattr(api_routes_module, "mcp", fake_mcp)

    resp = client.post("/api/tools/nonexistent", json={})
    assert resp.status_code == 404


def test_call_tool_mcp_unavailable_returns_503(
    monkeypatch: Any, client: TestClient
) -> None:
    monkeypatch.setattr(api_routes_module, "mcp", None)
    resp = client.post("/api/tools/any", json={})
    assert resp.status_code == 503


def test_call_tool_with_structured_content(monkeypatch: Any, client: TestClient) -> None:
    """structured_content takes priority over text content."""
    fake_result = MagicMock()
    fake_result.structured_content = {"key": "value", "count": 42}
    fake_mcp = MagicMock()

    async def _call_tool(name: str, args: dict[str, Any]) -> Any:
        return fake_result

    fake_mcp.call_tool = _call_tool
    monkeypatch.setattr(api_routes_module, "mcp", fake_mcp)

    resp = client.post("/api/tools/myTool", json={"arg": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == {"key": "value", "count": 42}


# ---------------------------------------------------------------------------
# GET /api/stream  — minimal smoke test (no full SSE parsing)
# ---------------------------------------------------------------------------


def test_sse_stream_handshake(monkeypatch: Any, client: TestClient) -> None:
    """Reading the SSE response should include a 'stream.connected' event."""
    status_raw = _raw("dashboard.status", {"initialized": True})
    approvals_raw = _raw("approval.list", {"count": 0, "items": []})

    monkeypatch.setattr(api_routes_module, "dashboard_status", lambda: status_raw)
    monkeypatch.setattr(api_routes_module, "approval_list", lambda: approvals_raw)

    # Replace the generator so it yields just the handshake and then stops,
    # avoiding any asyncio.sleep() that would block the test indefinitely.
    async def _finite_generator() -> Any:
        handshake: dict[str, Any] = {
            "type": "stream.connected",
            "data": {},
            "meta": {"timestamp": _FIXED_TS},
        }
        yield {"event": "message", "data": json.dumps(handshake)}

    monkeypatch.setattr(api_routes_module, "_sse_event_generator", _finite_generator)

    with client.stream("GET", "/api/stream") as response:
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type

        # Collect all lines (generator is finite)
        lines = list(response.iter_lines())

    raw_text = "\n".join(lines)
    assert "stream.connected" in raw_text


# ---------------------------------------------------------------------------
# _parse_envelope helper edge cases
# ---------------------------------------------------------------------------


def test_parse_envelope_invalid_json() -> None:
    from autopoiesis.server.api_routes import _parse_envelope  # pyright: ignore[reportPrivateUsage]

    result = _parse_envelope("not json at all {{{")
    assert result["type"] == "error.parse"
    assert "Invalid envelope" in result["data"]["message"]


def test_tool_result_to_dict_fallback_to_model_dump() -> None:
    """When content is empty and there's no structured_content, fall back to model_dump."""
    from autopoiesis.server.api_routes import _tool_result_to_dict  # pyright: ignore[reportPrivateUsage]

    fake = MagicMock()
    fake.structured_content = None
    fake.content = []
    fake.model_dump.return_value = {"fallback": True}
    result = _tool_result_to_dict(fake)
    assert result == {"fallback": True}
