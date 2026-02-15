"""Tests for Phase 1 approval envelope integrity and key management."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from approval_keys import ApprovalKeyManager, KeyPaths
from approval_policy import ToolClassification, ToolPolicyRegistry
from approval_store import ApprovalStore
from approval_types import (
    ApprovalScope,
    ApprovalVerificationError,
    DeferredToolCall,
    SignedDecision,
)

_TTL_SECONDS = 3600
_RETENTION_SECONDS = 7 * 24 * 3600
_CLOCK_SKEW_SECONDS = 60


def _store(db_path: Path, *, ttl_seconds: int = _TTL_SECONDS) -> ApprovalStore:
    return ApprovalStore(
        db_path=db_path,
        ttl_seconds=ttl_seconds,
        nonce_retention_seconds=_RETENTION_SECONDS,
        clock_skew_seconds=_CLOCK_SKEW_SECONDS,
    )


def _scope(work_item_id: str) -> ApprovalScope:
    return ApprovalScope(
        work_item_id=work_item_id,
        workspace_root="/tmp/workspace",
        agent_name="chat",
    )


def _tool_calls() -> list[DeferredToolCall]:
    return [{"tool_call_id": "call-1", "tool_name": "write_file", "args": {"path": "a.txt"}}]


def _paths(tmp_path: Path) -> KeyPaths:
    key_dir = tmp_path / "keys"
    return KeyPaths(
        key_dir=key_dir,
        private_key_path=key_dir / "approval.key",
        public_key_path=key_dir / "approval.pub",
        keyring_path=key_dir / "keyring.json",
    )


def _unlocked_key_manager(tmp_path: Path, *, passphrase: str = "passphrase") -> ApprovalKeyManager:
    manager = ApprovalKeyManager(_paths(tmp_path))
    manager.create_initial_key(passphrase)
    manager.unlock(passphrase)
    return manager


def _submission(nonce: str, decisions: list[dict[str, Any]]) -> str:
    return json.dumps({"nonce": nonce, "decisions": decisions}, ensure_ascii=True, allow_nan=False)


def _pending_state(db_path: Path, nonce: str) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT state FROM approval_envelopes WHERE nonce = ?",
            (nonce,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def _create_signed_envelope(
    *,
    store: ApprovalStore,
    scope: ApprovalScope,
    key_manager: ApprovalKeyManager,
) -> tuple[str, list[dict[str, Any]]]:
    tool_calls = _tool_calls()
    nonce, _ = store.create_envelope(
        scope=scope,
        tool_calls=tool_calls,
        key_id=key_manager.current_key_id(),
    )
    signed_decisions: list[SignedDecision] = [{"tool_call_id": "call-1", "approved": True}]
    store.store_signed_approval(
        nonce=nonce,
        decisions=signed_decisions,
        key_manager=key_manager,
    )
    decisions = [{"tool_call_id": "call-1", "approved": True, "denial_message": None}]
    return nonce, decisions


def test_verify_and_consume_happy_path(tmp_path: Path) -> None:
    store = _store(tmp_path / "approvals.sqlite")
    key_manager = _unlocked_key_manager(tmp_path)
    scope = _scope("w1")
    nonce, decisions = _create_signed_envelope(store=store, scope=scope, key_manager=key_manager)

    result = store.verify_and_consume(
        submission_json=_submission(nonce, decisions),
        live_scope=scope,
        key_manager=key_manager,
    )

    assert result[0]["tool_call_id"] == "call-1"
    assert result[0]["approved"] is True


def test_verify_rejects_replay(tmp_path: Path) -> None:
    store = _store(tmp_path / "approvals.sqlite")
    key_manager = _unlocked_key_manager(tmp_path)
    scope = _scope("w2")
    nonce, decisions = _create_signed_envelope(store=store, scope=scope, key_manager=key_manager)
    submission_json = _submission(nonce, decisions)

    store.verify_and_consume(
        submission_json=submission_json,
        live_scope=scope,
        key_manager=key_manager,
    )
    with pytest.raises(ApprovalVerificationError) as exc:
        store.verify_and_consume(
            submission_json=submission_json,
            live_scope=scope,
            key_manager=key_manager,
        )
    assert exc.value.code == "expired_or_consumed"


def test_context_drift_does_not_consume_nonce(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    store = _store(db_path)
    key_manager = _unlocked_key_manager(tmp_path)
    scope = _scope("w3")
    nonce, decisions = _create_signed_envelope(store=store, scope=scope, key_manager=key_manager)
    drifted_scope = ApprovalScope(
        work_item_id=scope.work_item_id,
        workspace_root="/tmp/other-workspace",
        agent_name=scope.agent_name,
    )

    with pytest.raises(ApprovalVerificationError) as exc:
        store.verify_and_consume(
            submission_json=_submission(nonce, decisions),
            live_scope=drifted_scope,
            key_manager=key_manager,
        )
    assert exc.value.code == "context_drift"
    assert _pending_state(db_path, nonce) == "pending"


def test_invalid_submission_does_not_consume_nonce(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    store = _store(db_path)
    key_manager = _unlocked_key_manager(tmp_path)
    scope = _scope("w4")
    nonce, _decisions = _create_signed_envelope(store=store, scope=scope, key_manager=key_manager)
    invalid = _submission(
        nonce,
        [{"tool_call_id": "call-1", "approved": "yes", "denial_message": None}],
    )

    with pytest.raises(ApprovalVerificationError) as exc:
        store.verify_and_consume(
            submission_json=invalid,
            live_scope=scope,
            key_manager=key_manager,
        )
    assert exc.value.code == "invalid_submission"
    assert _pending_state(db_path, nonce) == "pending"


def test_invalid_signature_does_not_consume_nonce(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    store = _store(db_path)
    key_manager = _unlocked_key_manager(tmp_path)
    scope = _scope("w5")
    nonce, decisions = _create_signed_envelope(store=store, scope=scope, key_manager=key_manager)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE approval_envelopes SET signature_hex = ? WHERE nonce = ?",
            ("00", nonce),
        )

    with pytest.raises(ApprovalVerificationError) as exc:
        store.verify_and_consume(
            submission_json=_submission(nonce, decisions),
            live_scope=scope,
            key_manager=key_manager,
        )
    assert exc.value.code == "invalid_signature"
    assert _pending_state(db_path, nonce) == "pending"


def test_unknown_key_id_does_not_consume_nonce(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    store = _store(db_path)
    key_manager = _unlocked_key_manager(tmp_path)
    scope = _scope("w6")
    nonce, decisions = _create_signed_envelope(store=store, scope=scope, key_manager=key_manager)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE approval_envelopes SET key_id = ? WHERE nonce = ?",
            ("missing-key-id", nonce),
        )

    with pytest.raises(ApprovalVerificationError) as exc:
        store.verify_and_consume(
            submission_json=_submission(nonce, decisions),
            live_scope=scope,
            key_manager=key_manager,
        )
    assert exc.value.code == "unknown_key_id"
    assert _pending_state(db_path, nonce) == "pending"


def test_scope_schema_unsupported_does_not_consume_nonce(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    store = _store(db_path)
    key_manager = _unlocked_key_manager(tmp_path)
    scope = _scope("w7")
    nonce, decisions = _create_signed_envelope(store=store, scope=scope, key_manager=key_manager)
    with sqlite3.connect(db_path) as conn:
        raw_scope = conn.execute(
            "SELECT scope_json FROM approval_envelopes WHERE nonce = ?",
            (nonce,),
        ).fetchone()
        assert raw_scope is not None
        scope_payload = json.loads(str(raw_scope[0]))
        scope_payload["scope_schema_version"] = 999
        conn.execute(
            "UPDATE approval_envelopes SET scope_json = ? WHERE nonce = ?",
            (json.dumps(scope_payload), nonce),
        )

    with pytest.raises(ApprovalVerificationError) as exc:
        store.verify_and_consume(
            submission_json=_submission(nonce, decisions),
            live_scope=scope,
            key_manager=key_manager,
        )
    assert exc.value.code == "scope_schema_unsupported"
    assert _pending_state(db_path, nonce) == "pending"


def test_bijection_mismatch_does_not_consume_nonce(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    store = _store(db_path)
    key_manager = _unlocked_key_manager(tmp_path)
    scope = _scope("w8")
    nonce, _decisions = _create_signed_envelope(store=store, scope=scope, key_manager=key_manager)
    mismatched = _submission(
        nonce,
        [{"tool_call_id": "call-x", "approved": True, "denial_message": None}],
    )

    with pytest.raises(ApprovalVerificationError) as exc:
        store.verify_and_consume(
            submission_json=mismatched,
            live_scope=scope,
            key_manager=key_manager,
        )
    assert exc.value.code == "bijection_mismatch"
    assert _pending_state(db_path, nonce) == "pending"


def test_expiry_path_rejects_without_consuming(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    store = _store(db_path)
    key_manager = _unlocked_key_manager(tmp_path)
    scope = _scope("w9")
    nonce, decisions = _create_signed_envelope(store=store, scope=scope, key_manager=key_manager)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE approval_envelopes SET expires_at = 0 WHERE nonce = ?",
            (nonce,),
        )

    with pytest.raises(ApprovalVerificationError) as exc:
        store.verify_and_consume(
            submission_json=_submission(nonce, decisions),
            live_scope=scope,
            key_manager=key_manager,
        )
    assert exc.value.code == "expired_or_consumed"
    assert _pending_state(db_path, nonce) == "pending"


def test_migration_expires_legacy_pending_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE approval_envelopes (
                nonce TEXT PRIMARY KEY,
                work_item_id TEXT NOT NULL,
                scope_json TEXT NOT NULL,
                tool_calls_json TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                issued_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO approval_envelopes
            (
                nonce, work_item_id, scope_json, tool_calls_json, plan_hash, state,
                issued_at, expires_at, consumed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("legacy-pending", "w10", "{}", "[]", "h1", "pending", 1, 2, None),
        )
        conn.execute(
            """
            INSERT INTO approval_envelopes
            (
                nonce, work_item_id, scope_json, tool_calls_json, plan_hash, state,
                issued_at, expires_at, consumed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("legacy-consumed", "w11", "{}", "[]", "h2", "consumed", 1, 2, 1),
        )

    _store(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT nonce, state, consumed_at FROM approval_envelopes ORDER BY nonce"
        ).fetchall()
    states = {str(row[0]): (str(row[1]), row[2]) for row in rows}
    assert states["legacy-pending"][0] == "expired"
    assert states["legacy-pending"][1] is not None
    assert states["legacy-consumed"][0] == "consumed"


def test_tool_policy_defaults_unknown_to_side_effecting() -> None:
    registry = ToolPolicyRegistry.default()
    assert registry.classify("new_tool") == ToolClassification.SIDE_EFFECTING
    with pytest.raises(ApprovalVerificationError) as exc:
        registry.validate_deferred_calls(
            [{"tool_call_id": "c1", "tool_name": "read", "args": {"path": "a.txt"}}]
        )
    assert exc.value.code == "tool_policy_violation"
    registry.validate_deferred_calls(
        [{"tool_call_id": "c2", "tool_name": "write_file", "args": {"path": "a.txt"}}]
    )


def test_unlock_rejects_wrong_passphrase(tmp_path: Path) -> None:
    manager = ApprovalKeyManager(_paths(tmp_path))
    manager.create_initial_key("correct-passphrase")
    with pytest.raises(SystemExit) as exc:
        manager.unlock("wrong-passphrase")
    assert "Invalid approval passphrase." in str(exc.value)


def test_rotation_invalidates_pending_envelopes(tmp_path: Path) -> None:
    db_path = tmp_path / "approvals.sqlite"
    store = _store(db_path)
    manager = _unlocked_key_manager(tmp_path, passphrase="old-passphrase")
    scope = _scope("w12")
    nonce, _ = store.create_envelope(
        scope=scope,
        tool_calls=_tool_calls(),
        key_id=manager.current_key_id(),
    )
    previous_key_id = manager.current_key_id()

    manager.rotate_key(
        current_passphrase="old-passphrase",
        new_passphrase="new-passphrase",
        expire_pending_envelopes=store.expire_pending_envelopes,
    )

    assert manager.current_key_id() != previous_key_id
    assert _pending_state(db_path, nonce) == "expired"


def test_retention_config_invariant_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPROVAL_TTL_SECONDS", "3600")
    monkeypatch.setenv("NONCE_RETENTION_PERIOD_SECONDS", "3000")
    monkeypatch.setenv("APPROVAL_CLOCK_SKEW_SECONDS", "60")
    monkeypatch.setenv("APPROVAL_DB_PATH", str(tmp_path / "approvals.sqlite"))
    with pytest.raises(SystemExit) as exc:
        ApprovalStore.from_env(base_dir=tmp_path)
    assert "NONCE_RETENTION_PERIOD_SECONDS must be >=" in str(exc.value)
