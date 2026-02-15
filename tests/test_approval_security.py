"""Tests for deferred approval envelope integrity checks."""

import json
from pathlib import Path

import pytest

from approval_security import ApprovalScope, ApprovalStore, ApprovalVerificationError


def _store(db_path: Path) -> ApprovalStore:
    return ApprovalStore(db_path=db_path, ttl_seconds=3600)


def _scope(work_item_id: str) -> ApprovalScope:
    return ApprovalScope(
        work_item_id=work_item_id,
        workspace_root="/tmp/workspace",
        agent_name="chat",
    )


def _tool_calls() -> list[dict[str, object]]:
    return [{"tool_call_id": "call-1", "tool_name": "write_file", "args": {"path": "a.txt"}}]


def _submission(nonce: str) -> str:
    decisions = [{"tool_call_id": "call-1", "approved": True, "denial_message": None}]
    return json.dumps({"nonce": nonce, "decisions": decisions})


def test_verify_and_consume_happy_path(tmp_path: Path) -> None:
    store = _store(tmp_path / "approvals.sqlite")
    scope = _scope("w1")
    nonce, _ = store.create_envelope(scope=scope, tool_calls=_tool_calls())

    decisions = store.verify_and_consume(submission_json=_submission(nonce), live_scope=scope)

    assert decisions[0]["tool_call_id"] == "call-1"
    assert decisions[0]["approved"] is True


def test_verify_rejects_replay(tmp_path: Path) -> None:
    store = _store(tmp_path / "approvals.sqlite")
    scope = _scope("w2")
    nonce, _ = store.create_envelope(scope=scope, tool_calls=_tool_calls())
    submission_json = _submission(nonce)

    store.verify_and_consume(submission_json=submission_json, live_scope=scope)

    with pytest.raises(ApprovalVerificationError) as exc:
        store.verify_and_consume(submission_json=submission_json, live_scope=scope)
    assert exc.value.code == "expired_or_consumed"


def test_drift_rejection_does_not_consume_nonce(tmp_path: Path) -> None:
    store = _store(tmp_path / "approvals.sqlite")
    original_scope = _scope("w3")
    nonce, _ = store.create_envelope(scope=original_scope, tool_calls=_tool_calls())
    submission_json = _submission(nonce)
    drifted_scope = ApprovalScope(
        work_item_id="w3",
        workspace_root="/tmp/other-workspace",
        agent_name="chat",
    )

    with pytest.raises(ApprovalVerificationError) as exc:
        store.verify_and_consume(submission_json=submission_json, live_scope=drifted_scope)
    assert exc.value.code == "context_drift"

    # The failed attempt must not burn the nonce.
    decisions = store.verify_and_consume(submission_json=submission_json, live_scope=original_scope)
    assert decisions[0]["tool_call_id"] == "call-1"
