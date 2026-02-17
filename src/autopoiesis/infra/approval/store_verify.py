"""Verification and parsing helpers for approval submissions.

Dependencies: approval.keys, approval.types
Wired in: approval/store.py → ApprovalStore.submit()
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, cast

from autopoiesis.infra.approval.keys import ApprovalKeyManager
from autopoiesis.infra.approval.types import (
    SIGNED_OBJECT_CONTEXT,
    ApprovalVerificationError,
    SignedDecision,
    SubmittedDecision,
)


def verify_signature_stage(*, row: sqlite3.Row, key_manager: ApprovalKeyManager) -> None:
    """Validate signature metadata and cryptographic signature."""
    key_id = str(row["key_id"])
    signed_payload = row["signed_object_json"]
    signature_hex = row["signature_hex"]
    if not key_id:
        raise ApprovalVerificationError("unknown_key_id", "Approval envelope key id is missing.")
    if not isinstance(signed_payload, str) or not signed_payload:
        raise ApprovalVerificationError(
            "invalid_signature",
            "Approval signature payload is missing.",
        )
    if not isinstance(signature_hex, str) or not signature_hex:
        raise ApprovalVerificationError("invalid_signature", "Approval signature is missing.")
    if key_manager.resolve_public_key(key_id) is None:
        raise ApprovalVerificationError("unknown_key_id", "Verification key not found.")
    if not key_manager.verify_signature(key_id, signed_payload, signature_hex):
        raise ApprovalVerificationError(
            "invalid_signature",
            "Approval signature verification failed.",
        )


def verify_signed_decisions(*, row: sqlite3.Row, signed_decisions: list[SignedDecision]) -> None:
    """Ensure signed payload contents match envelope and submitted decisions."""
    signed_payload = row["signed_object_json"]
    if not isinstance(signed_payload, str):
        raise ApprovalVerificationError("invalid_signature", "Signed payload missing.")
    try:
        loaded = json.loads(signed_payload)
    except json.JSONDecodeError as exc:
        raise ApprovalVerificationError(
            "invalid_signature",
            "Signed payload JSON is invalid.",
        ) from exc
    if not isinstance(loaded, dict):
        raise ApprovalVerificationError("invalid_signature", "Signed payload shape is invalid.")

    signed_object = cast(dict[str, Any], loaded)
    if signed_object.get("ctx") != SIGNED_OBJECT_CONTEXT:
        raise ApprovalVerificationError("invalid_signature", "Signed payload context is invalid.")
    if signed_object.get("nonce") != str(row["nonce"]):
        raise ApprovalVerificationError("invalid_signature", "Signed payload nonce mismatch.")
    if signed_object.get("plan_hash") != str(row["plan_hash"]):
        raise ApprovalVerificationError("invalid_signature", "Signed payload plan_hash mismatch.")
    if signed_object.get("key_id") != str(row["key_id"]):
        raise ApprovalVerificationError("invalid_signature", "Signed payload key_id mismatch.")

    signed_payload_decisions = signed_object.get("decisions")
    if not isinstance(signed_payload_decisions, list):
        raise ApprovalVerificationError(
            "invalid_signature",
            "Signed payload decisions are invalid.",
        )
    if signed_payload_decisions != signed_decisions:
        raise ApprovalVerificationError(
            "bijection_mismatch",
            "Submitted approvals do not match signed decisions.",
        )


def verify_bijection(
    tool_call_ids: list[str],
    submitted_decisions: list[SubmittedDecision],
) -> None:
    """Ensure submitted approvals map 1:1 to the original call order."""
    submitted_ids = [item["tool_call_id"] for item in submitted_decisions]
    if submitted_ids != tool_call_ids:
        raise ApprovalVerificationError(
            "bijection_mismatch",
            "Approval decisions do not match requested tool calls.",
        )


def parse_submission(submission_json: str) -> tuple[str, list[SubmittedDecision]]:
    """Parse and validate submission payload into nonce and decisions."""
    try:
        loaded = json.loads(submission_json)
    except json.JSONDecodeError as exc:
        raise ApprovalVerificationError(
            "invalid_submission",
            "Approval submission is not valid JSON.",
        ) from exc
    if not isinstance(loaded, dict):
        raise ApprovalVerificationError(
            "invalid_submission",
            "Approval submission must be a JSON object.",
        )

    payload = cast(dict[str, Any], loaded)
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise ApprovalVerificationError(
            "invalid_submission",
            "Approval submission nonce is missing.",
        )

    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise ApprovalVerificationError(
            "invalid_submission",
            "Approval submission decisions are missing.",
        )

    normalized = [validate_submitted_decision(item) for item in cast(list[Any], decisions)]
    return nonce, normalized


def validate_submitted_decision(raw: Any) -> SubmittedDecision:
    """Validate one submitted decision object."""
    if not isinstance(raw, dict):
        raise ApprovalVerificationError(
            "invalid_submission",
            "Approval decision entry must be an object.",
        )

    item = cast(dict[str, Any], raw)
    tool_call_id = item.get("tool_call_id")
    approved = item.get("approved")
    denial_message = item.get("denial_message")
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise ApprovalVerificationError(
            "invalid_submission",
            "Approval decision tool_call_id is invalid.",
        )
    if not isinstance(approved, bool):
        raise ApprovalVerificationError(
            "invalid_submission",
            "Approval decision approved must be boolean.",
        )
    if denial_message is not None and not isinstance(denial_message, str):
        raise ApprovalVerificationError(
            "invalid_submission",
            "Approval decision denial_message must be string or null.",
        )
    return {
        "tool_call_id": tool_call_id,
        "approved": approved,
        "denial_message": denial_message,
    }
