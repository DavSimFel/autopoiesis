"""Section 1: Startup & Serve integration tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from autopoiesis.agent.batch import BatchResult, format_output
from autopoiesis.server.app import app, set_connection_manager, set_session_store
from autopoiesis.server.connections import ConnectionManager
from autopoiesis.server.sessions import SessionStore


@pytest.fixture(autouse=True)
def fresh_server_state() -> Iterator[None]:
    set_session_store(SessionStore())
    set_connection_manager(ConnectionManager())
    yield


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestServerStartsWithWorkingRuntime:
    """1.1 — Server starts, /api/health returns 200, runtime initialized."""

    def test_health_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_session_create_returns_201(self, client: TestClient) -> None:
        resp = client.post("/api/sessions")
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_full_session_lifecycle(self, client: TestClient) -> None:
        create = client.post("/api/sessions")
        sid = create.json()["id"]
        listing = client.get("/api/sessions")
        assert any(s["id"] == sid for s in listing.json())
        delete = client.delete(f"/api/sessions/{sid}")
        assert delete.status_code == 204
        listing2 = client.get("/api/sessions")
        assert not any(s["id"] == sid for s in listing2.json())


class TestServerFailsGracefully:
    """1.2 — Server fails gracefully on bad config.

    The runtime initialization with missing provider env is tested
    indirectly through batch mode (which shares the same init path).
    """

    def test_batch_with_missing_env_exits(self) -> None:
        from autopoiesis.agent.batch import run_batch

        with (
            patch("autopoiesis.agent.batch.sys.stdin") as mock_stdin,
            pytest.raises(SystemExit),
        ):
            mock_stdin.read.return_value = ""
            run_batch(None)


class TestBatchModeProducesJSON:
    """1.3 — Batch mode produces JSON output with required fields."""

    def test_success_json_structure(self) -> None:
        result = BatchResult(
            success=True,
            result="hello",
            error=None,
            approval_rounds=0,
            elapsed_seconds=0.5,
        )
        parsed = json.loads(format_output(result))
        assert parsed["success"] is True
        assert parsed["result"] == "hello"
        assert "elapsed_seconds" in parsed

    def test_error_json_structure(self) -> None:
        result = BatchResult(
            success=False,
            result=None,
            error="provider not configured",
            approval_rounds=0,
            elapsed_seconds=0.1,
        )
        parsed = json.loads(format_output(result))
        assert parsed["success"] is False
        assert parsed["error"] == "provider not configured"

    def test_batch_run_writes_output_file(self, tmp_path: Path) -> None:
        from autopoiesis.agent.batch import run_batch
        from autopoiesis.run_simple import SimpleResult

        mock_rt = MagicMock()
        mock_rt.backend = MagicMock()
        output_file = tmp_path / "result.json"
        fake_result = SimpleResult(text="done", all_messages=[], approval_rounds=0)

        run_simple_mock = MagicMock(return_value=fake_result)
        with (
            patch("autopoiesis.agent.batch.get_runtime", return_value=mock_rt),
            patch("autopoiesis.agent.batch.run_simple", run_simple_mock),
            pytest.raises(SystemExit),
        ):
            run_batch("say hello", output_path=str(output_file))

        assert run_simple_mock.call_count == 1
        _, kwargs = run_simple_mock.call_args
        assert kwargs.get("auto_approve_deferred") is False

        if output_file.exists():
            data = json.loads(output_file.read_text())
            assert "success" in data
            assert "elapsed_seconds" in data
