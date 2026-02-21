"""Tests for the FastMCP server wrapper module."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from autopoiesis.db import open_db
from autopoiesis.infra.approval.store_schema import init_schema, utc_now_epoch
from autopoiesis.server import mcp_server


class _FakeFastMCP:
    def __init__(self, name: str) -> None:
        self.name = name
        self.tools: dict[str, Callable[..., Any]] = {}

    def tool(self, *, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _register(func: Callable[..., Any]) -> Callable[..., Any]:
            self.tools[name] = func
            return func

        return _register


class _Notifier:
    def __init__(self) -> None:
        self.called = 0

    async def notify_tool_list_changed(self) -> None:
        self.called += 1


def _insert_pending_approval(
    db_path: Path,
    *,
    envelope_id: str,
    nonce: str,
) -> None:
    tool_calls = json.dumps(
        [{"tool_call_id": "call-1", "tool_name": "execute", "args": {"command": "echo hi"}}],
        ensure_ascii=True,
        allow_nan=False,
    )
    now = utc_now_epoch()
    with closing(open_db(db_path)) as conn, conn:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO approval_envelopes (
                envelope_id, nonce, scope_json, tool_calls_json, plan_hash, key_id,
                signed_object_json, signature_hex, state, issued_at, expires_at, consumed_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 'pending', ?, ?, NULL)
            """,
            (
                envelope_id,
                nonce,
                "{}",
                tool_calls,
                "deadbeefcafebabe",
                "key-1",
                now,
                now + 3600,
            ),
        )


def _runtime_with_store(db_path: Path) -> Any:
    approval_store = MagicMock()
    approval_store._db_path = db_path
    return SimpleNamespace(
        agent_name="chat",
        approval_unlocked=False,
        shell_tier="review",
        approval_store=approval_store,
    )


def _approval_state(db_path: Path, envelope_id: str) -> str:
    with closing(open_db(db_path)) as conn:
        row = conn.execute(
            "SELECT state FROM approval_envelopes WHERE envelope_id = ?",
            (envelope_id,),
        ).fetchone()
    if row is None:
        raise AssertionError(f"Missing approval row for {envelope_id}")
    return str(row["state"])


def test_create_mcp_server_registers_core_tools() -> None:
    server = mcp_server.create_mcp_server(_FakeFastMCP)
    assert isinstance(server, _FakeFastMCP)
    assert sorted(server.tools) == [
        "approval.decide",
        "approval.list",
        "dashboard.status",
        "system.info",
    ]


def test_dashboard_status_returns_envelope(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "approvals.sqlite"
    _insert_pending_approval(db_path, envelope_id="env-1", nonce="nonce-1")
    runtime = _runtime_with_store(db_path)
    monkeypatch.setattr(mcp_server, "get_runtime", cast(Any, lambda: runtime))

    payload = json.loads(mcp_server.dashboard_status())

    assert payload["type"] == "dashboard.status"
    assert payload["data"]["initialized"] is True
    assert payload["data"]["agent_name"] == "chat"
    assert payload["data"]["pending_approvals_count"] == 1


def test_approval_list_returns_pending_items(monkeypatch: Any, tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    _insert_pending_approval(db_path, envelope_id="env-1", nonce="nonce-1")
    _insert_pending_approval(db_path, envelope_id="env-2", nonce="nonce-2")
    runtime = _runtime_with_store(db_path)
    monkeypatch.setattr(mcp_server, "get_runtime", cast(Any, lambda: runtime))

    payload = json.loads(mcp_server.approval_list())

    assert payload["type"] == "approval.list"
    assert payload["data"]["count"] == 2
    assert payload["data"]["items"][0]["id"] == "env-1"
    assert payload["data"]["items"][0]["tool_count"] == 1


def test_approval_decide_updates_state_and_emits_notification(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "approvals.sqlite"
    _insert_pending_approval(db_path, envelope_id="env-1", nonce="nonce-1")
    runtime = _runtime_with_store(db_path)
    notifier = _Notifier()
    monkeypatch.setattr(mcp_server, "get_runtime", cast(Any, lambda: runtime))
    monkeypatch.setattr(mcp_server, "mcp", notifier)

    payload = json.loads(asyncio.run(mcp_server.approval_decide("env-1", True)))

    assert payload["type"] == "approval.decision"
    assert payload["data"]["id"] == "env-1"
    assert payload["data"]["state"] == "consumed"
    assert payload["meta"]["notification_emitted"] is True
    assert notifier.called == 1
    assert _approval_state(db_path, "env-1") == "consumed"
