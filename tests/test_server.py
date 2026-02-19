"""Tests for the FastAPI server module."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from autopoiesis.agent.worker import DeferredApprovalLockedError
from autopoiesis.server.app import app, get_session_store, set_connection_manager, set_session_store
from autopoiesis.server.connections import ConnectionManager
from autopoiesis.server.models import WSIncoming, WSOutgoing
from autopoiesis.server.sessions import SessionStore


@pytest.fixture(autouse=True)
def fresh_stores() -> Iterator[None]:
    """Reset global stores between tests."""
    old_sessions = get_session_store()
    old_manager = ConnectionManager()
    set_session_store(SessionStore())
    set_connection_manager(ConnectionManager())
    yield
    set_session_store(old_sessions)
    set_connection_manager(old_manager)


@pytest.fixture()
def client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


class TestHealth:
    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestSessions:
    def test_create_session(self, client: TestClient) -> None:
        resp = client.post("/api/sessions")
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["message_count"] == 0

    def test_list_sessions_empty(self, client: TestClient) -> None:
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_sessions_after_create(self, client: TestClient) -> None:
        client.post("/api/sessions")
        client.post("/api/sessions")
        resp = client.get("/api/sessions")
        assert len(resp.json()) == 2

    def test_get_history_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/sessions/nonexistent/history")
        assert resp.status_code == 404

    def test_get_history_empty(self, client: TestClient) -> None:
        create_resp = client.post("/api/sessions")
        sid = create_resp.json()["id"]
        resp = client.get(f"/api/sessions/{sid}/history")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_delete_session(self, client: TestClient) -> None:
        create_resp = client.post("/api/sessions")
        sid = create_resp.json()["id"]
        resp = client.delete(f"/api/sessions/{sid}")
        assert resp.status_code == 204
        # Verify gone
        resp = client.get(f"/api/sessions/{sid}/history")
        assert resp.status_code == 404

    def test_delete_nonexistent(self, client: TestClient) -> None:
        resp = client.delete("/api/sessions/nonexistent")
        assert resp.status_code == 404


class TestAuth:
    def test_no_auth_required_when_no_key_set(self, client: TestClient) -> None:
        resp = client.get("/api/sessions")
        assert resp.status_code == 200

    def test_auth_required_when_key_set(self, client: TestClient) -> None:
        with patch("autopoiesis.server.auth.get_api_key", return_value="test-secret"):
            resp = client.get("/api/sessions")
            assert resp.status_code == 401

    def test_auth_succeeds_with_correct_key(self, client: TestClient) -> None:
        with patch("autopoiesis.server.auth.get_api_key", return_value="test-secret"):
            resp = client.get("/api/sessions", headers={"X-API-Key": "test-secret"})
            assert resp.status_code == 200

    def test_auth_fails_with_wrong_key(self, client: TestClient) -> None:
        with patch("autopoiesis.server.auth.get_api_key", return_value="test-secret"):
            resp = client.get("/api/sessions", headers={"X-API-Key": "wrong"})
            assert resp.status_code == 401


class TestWebSocket:
    def test_websocket_connect_and_invalid_message(self, client: TestClient) -> None:
        with client.websocket_connect("/api/ws/test-session") as ws:
            ws.send_text("not json")
            resp = ws.receive_json()
            assert resp["op"] == "error"

    def test_websocket_unknown_op(self, client: TestClient) -> None:
        with client.websocket_connect("/api/ws/test-session") as ws:
            ws.send_json({"op": "unknown", "data": {}})
            resp = ws.receive_json()
            assert resp["op"] == "error"
            assert "Unknown op" in resp["data"]["message"]

    def test_websocket_empty_message(self, client: TestClient) -> None:
        with client.websocket_connect("/api/ws/test-session") as ws:
            ws.send_json({"op": "message", "data": {"content": ""}})
            resp = ws.receive_json()
            assert resp["op"] == "error"
            assert "Empty" in resp["data"]["message"]

    def test_websocket_creates_session_on_connect(self, client: TestClient) -> None:
        store = get_session_store()
        with client.websocket_connect("/api/ws/auto-session"):
            assert store.exists("auto-session")

    def test_websocket_approve_returns_unsupported(self, client: TestClient) -> None:
        with client.websocket_connect("/api/ws/test-session") as ws:
            ws.send_json({"op": "approve", "data": {"request_id": "abc", "approved": True}})
            resp = ws.receive_json()
            assert resp["op"] == "error"
            assert resp["data"]["code"] == "approval_unsupported"

    def test_websocket_message_with_deferred_returns_unsupported(self, client: TestClient) -> None:
        deferred_output = type(
            "DeferredOutput",
            (),
            {
                "text": None,
                "message_history_json": "[]",
                "deferred_tool_requests_json": '{"nonce":"abc","requests":[]}',
            },
        )()
        with (
            patch("autopoiesis.agent.runtime.get_runtime"),
            patch("autopoiesis.agent.worker.enqueue_and_wait", return_value=deferred_output),
            patch("autopoiesis.display.streaming.register_stream"),
            client.websocket_connect("/api/ws/test-session") as ws,
        ):
            ws.send_json({"op": "message", "data": {"content": "hello"}})
            resp = ws.receive_json()
            assert resp["op"] == "error"
            assert resp["data"]["code"] == "approval_unsupported"


class TestChatEndpoint:
    def test_chat_returns_200_when_runtime_initialized(self, client: TestClient) -> None:
        """Serve bootstraps runtime; /api/chat returns 200 for valid requests."""
        mock_output = type(
            "MockOutput",
            (),
            {
                "text": "Hello back!",
                "message_history_json": "[]",
                "deferred_tool_requests_json": None,
            },
        )()
        with (
            patch("autopoiesis.agent.runtime.get_runtime"),
            patch("autopoiesis.agent.worker.enqueue_and_wait", return_value=mock_output),
            patch("autopoiesis.display.streaming.register_stream"),
        ):
            resp = client.post("/api/chat", json={"content": "hello"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "Hello back!"

    def test_chat_returns_503_when_runtime_init_fails(self, client: TestClient) -> None:
        """Graceful error when runtime init fails (e.g. missing provider config)."""
        with patch(
            "autopoiesis.agent.runtime.get_runtime",
            side_effect=RuntimeError("Runtime not initialised. Start the app via main()."),
        ):
            resp = client.post("/api/chat", json={"content": "hello"})
        assert resp.status_code == 503
        assert "Runtime not initialised" in resp.json()["detail"]

    def test_chat_returns_409_when_deferred_approvals_needed(self, client: TestClient) -> None:
        """Serve mode reports deferred approvals as unsupported."""
        mock_output = type(
            "DeferredOutput",
            (),
            {
                "text": None,
                "message_history_json": "[]",
                "deferred_tool_requests_json": '{"nonce":"abc","requests":[]}',
            },
        )()
        with (
            patch("autopoiesis.agent.runtime.get_runtime"),
            patch("autopoiesis.agent.worker.enqueue_and_wait", return_value=mock_output),
            patch("autopoiesis.display.streaming.register_stream"),
        ):
            resp = client.post("/api/chat", json={"content": "hello"})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "approval_unsupported"

    def test_chat_maps_locked_deferred_runtime_error_to_409(self, client: TestClient) -> None:
        """Worker deferred-lock errors map to approval_unsupported."""
        with (
            patch("autopoiesis.agent.runtime.get_runtime"),
            patch(
                "autopoiesis.agent.worker.enqueue_and_wait",
                side_effect=DeferredApprovalLockedError(
                    "Deferred approvals require unlocked approval keys."
                ),
            ),
            patch("autopoiesis.display.streaming.register_stream"),
        ):
            resp = client.post("/api/chat", json={"content": "hello"})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "approval_unsupported"


class TestConnectionManager:
    def test_client_count_empty(self) -> None:
        mgr = ConnectionManager()
        assert mgr.client_count("none") == 0

    def test_active_sessions_empty(self) -> None:
        mgr = ConnectionManager()
        assert mgr.active_sessions() == []


class TestSessionStore:
    def test_create_and_get(self) -> None:
        store = SessionStore()
        info = store.create("s1")
        assert info.id == "s1"
        assert store.get("s1") is not None
        assert store.exists("s1")

    def test_delete(self) -> None:
        store = SessionStore()
        store.create("s1")
        assert store.delete("s1")
        assert not store.exists("s1")
        assert not store.delete("s1")

    def test_history_roundtrip(self) -> None:
        store = SessionStore()
        store.create("s1")
        assert store.get_history_json("s1") is None
        store.set_history_json("s1", "[]")
        assert store.get_history_json("s1") == "[]"

    def test_remove_stale_respects_ttl(self) -> None:
        store = SessionStore()
        store.create("active")
        store.create("stale")
        # Backdate the stale session
        store.backdate_last_active("stale", datetime(2020, 1, 1, tzinfo=UTC))
        removed = store.remove_stale(ttl_seconds=60, active_sessions=set())
        assert "stale" in removed
        assert not store.exists("stale")
        assert store.exists("active")

    def test_remove_stale_skips_active_websocket(self) -> None:
        store = SessionStore()
        store.create("ws-active")
        store.backdate_last_active("ws-active", datetime(2020, 1, 1, tzinfo=UTC))
        removed = store.remove_stale(ttl_seconds=60, active_sessions={"ws-active"})
        assert removed == []
        assert store.exists("ws-active")


class TestWSModels:
    def test_incoming_model(self) -> None:
        msg = WSIncoming(op="message", data={"content": "hi"})
        assert msg.op == "message"

    def test_outgoing_model(self) -> None:
        msg = WSOutgoing(op="token", data={"content": "Hello"})
        dumped = msg.model_dump_json()
        assert "token" in dumped
