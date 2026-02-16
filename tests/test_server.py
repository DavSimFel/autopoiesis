"""Tests for the FastAPI server module."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server.app import app, get_session_store, set_connection_manager, set_session_store
from server.connections import ConnectionManager
from server.models import WSIncoming, WSOutgoing
from server.sessions import SessionStore


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
        with patch("server.auth.get_api_key", return_value="test-secret"):
            resp = client.get("/api/sessions")
            assert resp.status_code == 401

    def test_auth_succeeds_with_correct_key(self, client: TestClient) -> None:
        with patch("server.auth.get_api_key", return_value="test-secret"):
            resp = client.get("/api/sessions", headers={"X-API-Key": "test-secret"})
            assert resp.status_code == 200

    def test_auth_fails_with_wrong_key(self, client: TestClient) -> None:
        with patch("server.auth.get_api_key", return_value="test-secret"):
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


class TestChatEndpoint:
    def test_chat_without_runtime_returns_503(self, client: TestClient) -> None:
        resp = client.post("/api/chat", json={"content": "hello"})
        assert resp.status_code == 503


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


class TestWSModels:
    def test_incoming_model(self) -> None:
        msg = WSIncoming(op="message", data={"content": "hi"})
        assert msg.op == "message"

    def test_outgoing_model(self) -> None:
        msg = WSOutgoing(op="token", data={"content": "Hello"})
        dumped = msg.model_dump_json()
        assert "token" in dumped
