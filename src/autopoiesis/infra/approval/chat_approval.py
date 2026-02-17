"""Approval scope construction and approval decision serialization helpers.

Dependencies: approval.keys, approval.policy, approval.store, approval.types
Wired in: agent/cli.py → cli_chat_loop(), agent/worker.py → run_agent_step()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic_ai import DeferredToolRequests
from pydantic_ai.tools import DeferredToolResults, ToolDenied
from pydantic_ai_backends import LocalBackend

from autopoiesis.infra.approval.keys import ApprovalKeyManager
from autopoiesis.infra.approval.policy import ToolPolicyRegistry
from autopoiesis.infra.approval.store import ApprovalStore
from autopoiesis.infra.approval.types import ApprovalScope, DeferredToolCall, SignedDecision

_APPROVE_CHOICES = ("", "y", "yes")
_DENY_CHOICES = ("n", "no")
_DEFAULT_DENIAL_MESSAGE = "User denied this action."


def build_approval_scope(
    approval_context_id: str,
    backend: LocalBackend,
    agent_name: str,
) -> ApprovalScope:
    """Build the signed approval scope for a work item context."""
    return ApprovalScope(
        work_item_id=approval_context_id,
        workspace_root=str(Path(backend.root_dir).resolve()),
        agent_name=agent_name,
    )


def serialize_deferred_requests(
    requests: DeferredToolRequests,
    *,
    scope: ApprovalScope,
    approval_store: ApprovalStore,
    key_manager: ApprovalKeyManager,
    tool_policy: ToolPolicyRegistry,
) -> str:
    """Serialize deferred requests and persist approval envelope."""
    data: list[DeferredToolCall] = [
        {
            "tool_call_id": call.tool_call_id,
            "tool_name": call.tool_name,
            "args": call.args,
        }
        for call in requests.approvals
    ]
    tool_policy.validate_deferred_calls(data)
    nonce, plan_hash = approval_store.create_envelope(
        scope=scope,
        tool_calls=data,
        key_id=key_manager.current_key_id(),
    )
    return json.dumps(
        {"nonce": nonce, "plan_hash_prefix": plan_hash[:8], "requests": data},
        ensure_ascii=True,
        allow_nan=False,
    )


def deserialize_deferred_results(
    results_json: str,
    *,
    scope: ApprovalScope,
    approval_store: ApprovalStore,
    key_manager: ApprovalKeyManager,
) -> DeferredToolResults:
    """Deserialize approved/denied tool decisions for agent resumption."""
    data = approval_store.verify_and_consume(
        submission_json=results_json,
        live_scope=scope,
        key_manager=key_manager,
    )
    results = DeferredToolResults()
    for entry in data:
        tool_call_id = entry["tool_call_id"]
        if entry["approved"]:
            results.approvals[tool_call_id] = True
            continue
        denial_message = entry.get("denial_message")
        message = (
            denial_message
            if isinstance(denial_message, str) and denial_message
            else _DEFAULT_DENIAL_MESSAGE
        )
        results.approvals[tool_call_id] = ToolDenied(message)
    return results


def display_approval_requests(requests_json: str) -> dict[str, Any]:
    """Display pending tool approval requests and return parsed payload."""
    payload: dict[str, Any] = json.loads(requests_json)
    requests = cast(list[dict[str, Any]], payload["requests"])
    print("\n🔒 Tool approval required:")
    print(f"  Plan hash: {payload['plan_hash_prefix']}")
    for i, req in enumerate(requests, 1):
        tool_name = req["tool_name"]
        args: Any = req["args"]
        print(f"  [{i}] {tool_name}")
        serialized = json.dumps(args, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
        print("      args:")
        for line in serialized.splitlines():
            print(f"        {line}")
    return payload


def gather_approvals(
    payload: dict[str, Any],
    *,
    approval_store: ApprovalStore,
    key_manager: ApprovalKeyManager,
) -> str:
    """Collect local user decisions, sign them, and return submission JSON."""
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise ValueError("Approval payload nonce is missing.")

    requests = cast(list[dict[str, Any]], payload["requests"])
    decisions = (
        _collect_single_decision(requests[0])
        if len(requests) == 1
        else _collect_batch_decisions(requests)
    )
    signed_decisions: list[SignedDecision] = [
        {"tool_call_id": str(item["tool_call_id"]), "approved": bool(item["approved"])}
        for item in decisions
    ]
    approval_store.store_signed_approval(
        nonce=nonce,
        decisions=signed_decisions,
        key_manager=key_manager,
    )
    return json.dumps({"nonce": nonce, "decisions": decisions}, ensure_ascii=True, allow_nan=False)


def _decision_entry(
    tool_call_id: str,
    approved: bool,
    denial_message: str | None = None,
) -> dict[str, Any]:
    resolved_denial = None
    if not approved:
        if isinstance(denial_message, str) and denial_message:
            resolved_denial = denial_message
        else:
            resolved_denial = _DEFAULT_DENIAL_MESSAGE
    return {
        "tool_call_id": tool_call_id,
        "approved": approved,
        "denial_message": resolved_denial,
    }


def _collect_single_decision(request: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        answer = input("  Approve? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return [_decision_entry(str(request["tool_call_id"]), False)]
    approved = answer in _APPROVE_CHOICES
    denial_message = _prompt_denial_reason() if not approved else None
    return [_decision_entry(str(request["tool_call_id"]), approved, denial_message)]


def _collect_batch_decisions(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        answer = input("  Approve all? [Y/n/pick] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return [_decision_entry(str(req["tool_call_id"]), False) for req in requests]

    if answer in _APPROVE_CHOICES:
        return [_decision_entry(str(req["tool_call_id"]), True) for req in requests]

    if answer in ("pick", "p"):
        decisions: list[dict[str, Any]] = []
        for i, req in enumerate(requests, 1):
            try:
                choice = input(f"  [{i}] {req['tool_name']} - approve? [Y/n] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                decisions.append(_decision_entry(str(req["tool_call_id"]), False))
                continue
            approved = choice in _APPROVE_CHOICES
            denial_message = _prompt_denial_reason() if not approved else None
            decisions.append(_decision_entry(str(req["tool_call_id"]), approved, denial_message))
        return decisions

    denial_message = _prompt_denial_reason()
    return [_decision_entry(str(req["tool_call_id"]), False, denial_message) for req in requests]


def _prompt_denial_reason() -> str | None:
    try:
        reason = input("  Denial reason (optional): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return reason if reason else None
