"""Tests for serialize_deferred_requests / deserialize_deferred_results round-trip."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from pydantic_ai.tools import ToolDenied

from approval.chat_approval import deserialize_deferred_results, serialize_deferred_requests
from approval.keys import ApprovalKeyManager
from approval.policy import ToolPolicyRegistry
from approval.store import ApprovalStore
from approval.types import ApprovalScope, SignedDecision


def _scope() -> ApprovalScope:
    return ApprovalScope(
        work_item_id="test-wid",
        workspace_root="/tmp/test",
        agent_name="test-agent",
    )


def _mock_deferred_requests(
    calls: list[dict[str, Any]],
) -> Any:
    """Build a mock DeferredToolRequests with the given call dicts."""
    mock = MagicMock()
    approvals: list[MagicMock] = []
    for c in calls:
        approval = MagicMock()
        approval.tool_call_id = c["tool_call_id"]
        approval.tool_name = c["tool_name"]
        approval.args = c["args"]
        approvals.append(approval)
    mock.approvals = approvals
    return mock


def test_serialize_round_trip_approve_all(
    approval_store: ApprovalStore,
    key_manager: ApprovalKeyManager,
) -> None:
    """Serialize requests then deserialize with all approved."""
    scope = _scope()
    policy = ToolPolicyRegistry.default()
    calls: list[dict[str, Any]] = [
        {"tool_call_id": "tc1", "tool_name": "write_file", "args": {"path": "/a"}},
        {"tool_call_id": "tc2", "tool_name": "execute", "args": {"cmd": "ls"}},
    ]
    requests = _mock_deferred_requests(calls)
    serialized: str = serialize_deferred_requests(
        requests,
        scope=scope,
        approval_store=approval_store,
        key_manager=key_manager,
        tool_policy=policy,
    )
    payload: dict[str, Any] = json.loads(serialized)
    assert "nonce" in payload
    assert "requests" in payload
    expected_count = 2
    assert len(payload["requests"]) == expected_count

    # Build approval submission
    decisions: list[SignedDecision] = [
        {"tool_call_id": "tc1", "approved": True},
        {"tool_call_id": "tc2", "approved": True},
    ]
    approval_store.store_signed_approval(
        nonce=payload["nonce"],
        decisions=decisions,
        key_manager=key_manager,
    )
    submission = json.dumps({"nonce": payload["nonce"], "decisions": decisions})

    results = deserialize_deferred_results(
        submission,
        scope=scope,
        approval_store=approval_store,
        key_manager=key_manager,
    )
    assert results.approvals["tc1"] is True
    assert results.approvals["tc2"] is True


def test_serialize_round_trip_deny(
    approval_store: ApprovalStore,
    key_manager: ApprovalKeyManager,
) -> None:
    """Denied tool call produces ToolDenied in results."""
    scope = _scope()
    policy = ToolPolicyRegistry.default()
    calls: list[dict[str, Any]] = [
        {"tool_call_id": "tc1", "tool_name": "execute", "args": {"cmd": "rm"}},
    ]
    requests = _mock_deferred_requests(calls)
    serialized: str = serialize_deferred_requests(
        requests,
        scope=scope,
        approval_store=approval_store,
        key_manager=key_manager,
        tool_policy=policy,
    )
    payload: dict[str, Any] = json.loads(serialized)
    decisions: list[SignedDecision] = [
        {"tool_call_id": "tc1", "approved": False},
    ]
    approval_store.store_signed_approval(
        nonce=payload["nonce"],
        decisions=decisions,
        key_manager=key_manager,
    )
    submission = json.dumps({"nonce": payload["nonce"], "decisions": decisions})

    results = deserialize_deferred_results(
        submission,
        scope=scope,
        approval_store=approval_store,
        key_manager=key_manager,
    )
    assert isinstance(results.approvals["tc1"], ToolDenied)


def test_serialize_produces_valid_json(
    approval_store: ApprovalStore,
    key_manager: ApprovalKeyManager,
) -> None:
    """Serialized output is valid JSON with expected structure."""
    scope = _scope()
    policy = ToolPolicyRegistry.default()
    calls: list[dict[str, Any]] = [
        {"tool_call_id": "tc1", "tool_name": "write_file", "args": {"path": "x"}},
    ]
    requests = _mock_deferred_requests(calls)
    serialized: str = serialize_deferred_requests(
        requests,
        scope=scope,
        approval_store=approval_store,
        key_manager=key_manager,
        tool_policy=policy,
    )
    payload: dict[str, Any] = json.loads(serialized)
    assert isinstance(payload["nonce"], str)
    assert isinstance(payload["plan_hash_prefix"], str)
    expected_prefix_len = 8
    assert len(payload["plan_hash_prefix"]) == expected_prefix_len
    assert payload["requests"][0]["tool_call_id"] == "tc1"
