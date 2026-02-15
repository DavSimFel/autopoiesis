"""Shared data models and canonicalization helpers for approval security."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, TypedDict, cast

SCOPE_SCHEMA_VERSION = 1
SIGNED_OBJECT_CONTEXT = "autopoiesis.approval.v1"
TOOLSET_MODE = "require_write_approval"


class ApprovalVerificationError(ValueError):
    """Raised when deferred approval verification fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DeferredToolCall(TypedDict):
    """Tool call shape persisted in approval envelopes."""

    tool_call_id: str
    tool_name: str
    args: Any


class SignedDecision(TypedDict):
    """Decision fields covered by the approval signature."""

    tool_call_id: str
    approved: bool


class SubmittedDecision(SignedDecision):
    """Decision fields submitted back to worker for execution."""

    denial_message: str | None


def _empty_string_list() -> list[str]:
    return []


@dataclass(frozen=True)
class ApprovalScope:
    """Execution scope bound to an approval envelope."""

    work_item_id: str
    workspace_root: str
    agent_name: str
    scope_schema_version: int = SCOPE_SCHEMA_VERSION
    tool_call_ids: list[str] = field(default_factory=_empty_string_list)
    toolset_mode: str = TOOLSET_MODE
    allowed_paths: list[str] | None = None
    max_cost_cents: int | None = None
    child_scope: bool | None = None
    parent_envelope_id: str | None = None
    session_id: str | None = None
    scope_tags: list[str] | None = None

    def with_tool_call_ids(self, tool_call_ids: list[str]) -> ApprovalScope:
        return ApprovalScope(
            work_item_id=self.work_item_id,
            workspace_root=self.workspace_root,
            agent_name=self.agent_name,
            scope_schema_version=self.scope_schema_version,
            tool_call_ids=tool_call_ids,
            toolset_mode=self.toolset_mode,
            allowed_paths=self.allowed_paths,
            max_cost_cents=self.max_cost_cents,
            child_scope=self.child_scope,
            parent_envelope_id=self.parent_envelope_id,
            session_id=self.session_id,
            scope_tags=self.scope_tags,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "scope_schema_version": self.scope_schema_version,
            "tool_call_ids": self.tool_call_ids,
            "workspace_root": self.workspace_root,
            "agent_name": self.agent_name,
            "toolset_mode": self.toolset_mode,
            "allowed_paths": self.allowed_paths,
            "max_cost_cents": self.max_cost_cents,
            "child_scope": self.child_scope,
            "parent_envelope_id": self.parent_envelope_id,
            "session_id": self.session_id,
            "scope_tags": self.scope_tags,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ApprovalScope:
        scope_version = raw.get("scope_schema_version")
        if scope_version != SCOPE_SCHEMA_VERSION:
            raise ApprovalVerificationError(
                "scope_schema_unsupported", "Unsupported approval scope schema version."
            )
        tool_call_ids = raw.get("tool_call_ids")
        if not isinstance(tool_call_ids, list):
            raise ApprovalVerificationError(
                "invalid_submission", "Approval scope tool_call_ids is malformed."
            )
        call_ids = cast(list[Any], tool_call_ids)
        if not all(isinstance(call_id, str) for call_id in call_ids):
            raise ApprovalVerificationError(
                "invalid_submission", "Approval scope tool_call_ids is malformed."
            )
        work_item_id = raw.get("work_item_id")
        workspace_root = raw.get("workspace_root")
        agent_name = raw.get("agent_name")
        toolset_mode = raw.get("toolset_mode")
        if not isinstance(work_item_id, str) or not work_item_id:
            raise ApprovalVerificationError(
                "invalid_submission", "Approval scope work_item_id is invalid."
            )
        if not isinstance(workspace_root, str) or not workspace_root:
            raise ApprovalVerificationError(
                "invalid_submission", "Approval scope workspace_root is invalid."
            )
        if not isinstance(agent_name, str) or not agent_name:
            raise ApprovalVerificationError(
                "invalid_submission", "Approval scope agent_name is invalid."
            )
        if not isinstance(toolset_mode, str) or not toolset_mode:
            raise ApprovalVerificationError(
                "invalid_submission", "Approval scope toolset_mode is invalid."
            )
        return cls(
            work_item_id=work_item_id,
            workspace_root=workspace_root,
            agent_name=agent_name,
            scope_schema_version=scope_version,
            tool_call_ids=cast(list[str], call_ids),
            toolset_mode=toolset_mode,
            allowed_paths=_as_optional_string_list(raw.get("allowed_paths")),
            max_cost_cents=_as_optional_int(raw.get("max_cost_cents")),
            child_scope=_as_optional_bool(raw.get("child_scope")),
            parent_envelope_id=_as_optional_str(raw.get("parent_envelope_id")),
            session_id=_as_optional_str(raw.get("session_id")),
            scope_tags=_as_optional_string_list(raw.get("scope_tags")),
        )


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def compute_plan_hash(scope: ApprovalScope, tool_calls: list[DeferredToolCall]) -> str:
    payload = {"scope": scope.to_dict(), "tool_calls": tool_calls}
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8"))
    return digest.hexdigest()


def signed_decisions_from_submitted(decisions: list[SubmittedDecision]) -> list[SignedDecision]:
    return [
        {"tool_call_id": item["tool_call_id"], "approved": item["approved"]}
        for item in decisions
    ]


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ApprovalVerificationError(
        "invalid_submission", "Approval scope field must be a string or null."
    )


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    raise ApprovalVerificationError(
        "invalid_submission", "Approval scope field must be an int or null."
    )


def _as_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ApprovalVerificationError(
        "invalid_submission", "Approval scope field must be a bool or null."
    )


def _as_optional_string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        items = cast(list[Any], value)
        if all(isinstance(item, str) for item in items):
            return cast(list[str], items)
    raise ApprovalVerificationError(
        "invalid_submission", "Approval scope field must be a list[str] or null."
    )
