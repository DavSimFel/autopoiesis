"""Approval envelope persistence and verification for deferred tool calls."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

_DEFAULT_DB_PATH = "data/approvals.sqlite"
_DEFAULT_TTL_SECONDS = 3600
_TOOLSET_MODE = "require_write_approval"


class ApprovalVerificationError(ValueError):
    """Raised when a deferred approval submission fails verification."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ApprovalScope:
    """Execution context that an approval envelope authorizes."""

    work_item_id: str
    workspace_root: str
    agent_name: str
    toolset_mode: str = _TOOLSET_MODE

    def to_json(self) -> dict[str, str]:
        return {
            "work_item_id": self.work_item_id,
            "workspace_root": self.workspace_root,
            "agent_name": self.agent_name,
            "toolset_mode": self.toolset_mode,
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _compute_plan_hash(scope: dict[str, str], tool_calls: list[dict[str, Any]]) -> str:
    payload = {"scope": scope, "tool_calls": tool_calls}
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8"))
    return digest.hexdigest()


def _resolve_approval_db_path() -> Path:
    explicit = os.getenv("APPROVAL_DB_PATH")
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else Path(__file__).resolve().parent / path
    db_url = os.getenv("DBOS_SYSTEM_DATABASE_URL", "sqlite:///dbostest.sqlite")
    if db_url.startswith("sqlite:///"):
        return Path(db_url.removeprefix("sqlite:///")).resolve()
    return (Path(__file__).resolve().parent / _DEFAULT_DB_PATH).resolve()


def approval_ttl_seconds() -> int:
    raw = os.getenv("APPROVAL_TTL_SECONDS", str(_DEFAULT_TTL_SECONDS))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit("APPROVAL_TTL_SECONDS must be an integer.") from exc
    if value <= 0:
        raise SystemExit("APPROVAL_TTL_SECONDS must be > 0.")
    return value


class ApprovalStore:
    """SQLite-backed storage for single-use approval envelopes."""

    def __init__(self, db_path: Path, ttl_seconds: int) -> None:
        self._db_path = db_path
        self._ttl_seconds = ttl_seconds
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @classmethod
    def from_env(cls) -> ApprovalStore:
        return cls(db_path=_resolve_approval_db_path(), ttl_seconds=approval_ttl_seconds())

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_envelopes (
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

    def create_envelope(
        self, *, scope: ApprovalScope, tool_calls: list[dict[str, Any]]
    ) -> tuple[str, str]:
        issued_at = int(datetime.now(UTC).timestamp())
        expires_at = issued_at + self._ttl_seconds
        nonce = uuid4().hex
        scope_json = scope.to_json()
        plan_hash = _compute_plan_hash(scope_json, tool_calls)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approval_envelopes (
                    nonce, work_item_id, scope_json, tool_calls_json,
                    plan_hash, state, issued_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    nonce,
                    scope.work_item_id,
                    _canonical_json(scope_json),
                    _canonical_json(tool_calls),
                    plan_hash,
                    issued_at,
                    expires_at,
                ),
            )
        return nonce, plan_hash

    def verify_and_consume(
        self, *, submission_json: str, live_scope: ApprovalScope
    ) -> list[dict[str, Any]]:
        submission = self._parse_submission(submission_json)
        nonce = submission["nonce"]
        decisions = submission["decisions"]
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT nonce, scope_json, tool_calls_json, plan_hash, state, expires_at
                FROM approval_envelopes
                WHERE nonce = ?
                """,
                (nonce,),
            ).fetchone()
            if row is None:
                raise ApprovalVerificationError("unknown_nonce", "Approval nonce was not found.")
            if row["state"] != "pending":
                raise ApprovalVerificationError(
                    "expired_or_consumed", "Approval nonce is already consumed or expired."
                )
            stored_scope = json.loads(str(row["scope_json"]))
            tool_calls = json.loads(str(row["tool_calls_json"]))
            expected_hash = str(row["plan_hash"])
            actual_hash = _compute_plan_hash(live_scope.to_json(), tool_calls)
            if stored_scope != live_scope.to_json() or actual_hash != expected_hash:
                raise ApprovalVerificationError(
                    "context_drift", "Execution context does not match the approved plan."
                )
            self._verify_bijection(tool_calls, decisions)
            now = int(datetime.now(UTC).timestamp())
            updated = conn.execute(
                """
                UPDATE approval_envelopes
                SET state = 'consumed', consumed_at = ?
                WHERE nonce = ? AND state = 'pending' AND expires_at > ?
                """,
                (now, nonce, now),
            )
            if updated.rowcount != 1:
                raise ApprovalVerificationError(
                    "expired_or_consumed", "Approval nonce is expired or already consumed."
                )
        return decisions

    def _parse_submission(self, submission_json: str) -> dict[str, Any]:
        try:
            payload: Any = json.loads(submission_json)
        except json.JSONDecodeError as exc:
            raise ApprovalVerificationError(
                "invalid_submission", "Approval submission is not JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise ApprovalVerificationError(
                "invalid_submission", "Approval submission must be an object."
            )
        payload_dict = cast(dict[str, Any], payload)
        nonce: Any = payload_dict.get("nonce")
        decisions: Any = payload_dict.get("decisions")
        if not isinstance(nonce, str) or not nonce:
            raise ApprovalVerificationError(
                "invalid_submission", "Approval submission is missing nonce."
            )
        if not isinstance(decisions, list):
            raise ApprovalVerificationError(
                "invalid_submission", "Approval submission is missing decisions."
            )
        return {"nonce": nonce, "decisions": decisions}

    def _verify_bijection(
        self, tool_calls: list[dict[str, Any]], decisions: list[dict[str, Any]]
    ) -> None:
        call_ids = [str(call["tool_call_id"]) for call in tool_calls]
        decision_ids = [str(entry.get("tool_call_id", "")) for entry in decisions]
        if call_ids != decision_ids:
            raise ApprovalVerificationError(
                "bijection_mismatch", "Approval decisions do not match requested tool calls."
            )
