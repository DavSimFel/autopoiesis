"""SQLite approval envelope storage and verification workflow.

Dependencies: approval.keys, approval.store_schema, approval.store_verify, approval.types
Wired in: chat.py → main(), agent/runtime.py → Runtime
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from autopoiesis.db import open_db
from autopoiesis.infra.approval.keys import ApprovalKeyManager
from autopoiesis.infra.approval.store_schema import init_schema, utc_now_epoch
from autopoiesis.infra.approval.store_verify import (
    parse_submission,
    verify_bijection,
    verify_signature_stage,
    verify_signed_decisions,
)
from autopoiesis.infra.approval.types import (
    ApprovalScope,
    ApprovalVerificationError,
    DeferredToolCall,
    SignedDecision,
    SubmittedDecision,
    canonical_json,
    compute_plan_hash,
    signed_decisions_from_submitted,
)

_DEFAULT_APPROVAL_TTL_SECONDS = 3600
_DEFAULT_NONCE_RETENTION_SECONDS = 7 * 24 * 3600
_DEFAULT_CLOCK_SKEW_SECONDS = 60


class ApprovalStore:
    """Persistent envelope store with schema migration and atomic consume semantics."""

    def __init__(
        self,
        *,
        db_path: Path,
        ttl_seconds: int,
        nonce_retention_seconds: int,
        clock_skew_seconds: int,
    ) -> None:
        self._db_path = db_path
        self._ttl_seconds = ttl_seconds
        self._nonce_retention_seconds = nonce_retention_seconds
        self._clock_skew_seconds = clock_skew_seconds
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            init_schema(conn)

    @classmethod
    def from_env(cls, *, base_dir: Path) -> ApprovalStore:
        ttl = _read_positive_int("APPROVAL_TTL_SECONDS", _DEFAULT_APPROVAL_TTL_SECONDS)
        retention = _read_positive_int(
            "NONCE_RETENTION_PERIOD_SECONDS",
            _DEFAULT_NONCE_RETENTION_SECONDS,
        )
        skew = _read_non_negative_int("APPROVAL_CLOCK_SKEW_SECONDS", _DEFAULT_CLOCK_SKEW_SECONDS)
        if retention < ttl + skew:
            raise SystemExit(
                "Invalid approval retention config: NONCE_RETENTION_PERIOD_SECONDS must be >= "
                "APPROVAL_TTL_SECONDS + APPROVAL_CLOCK_SKEW_SECONDS."
            )
        store = cls(
            db_path=_resolve_approval_db_path(base_dir),
            ttl_seconds=ttl,
            nonce_retention_seconds=retention,
            clock_skew_seconds=skew,
        )
        store.prune_expired_envelopes()
        return store

    def create_envelope(
        self,
        *,
        scope: ApprovalScope,
        tool_calls: list[DeferredToolCall],
        key_id: str,
    ) -> tuple[str, str]:
        issued_at = utc_now_epoch()
        expires_at = issued_at + self._ttl_seconds
        nonce = uuid4().hex
        envelope_id = str(uuid4())
        tool_call_ids = [call["tool_call_id"] for call in tool_calls]
        scoped = scope.with_tool_call_ids(tool_call_ids)
        plan_hash = compute_plan_hash(scoped, tool_calls)
        with closing(self._connect()) as conn, conn:
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
                    canonical_json(scoped.to_dict()),
                    canonical_json(tool_calls),
                    plan_hash,
                    key_id,
                    issued_at,
                    expires_at,
                ),
            )
        return nonce, plan_hash

    def store_signed_approval(
        self,
        *,
        nonce: str,
        decisions: list[SignedDecision],
        key_manager: ApprovalKeyManager,
    ) -> None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                """
                SELECT nonce, plan_hash, key_id, state
                FROM approval_envelopes
                WHERE nonce = ?
                """,
                (nonce,),
            ).fetchone()
            if row is None:
                raise ApprovalVerificationError("unknown_nonce", "Approval nonce was not found.")
            if row["state"] != "pending":
                raise ApprovalVerificationError(
                    "expired_or_consumed",
                    "Approval nonce is already consumed or expired.",
                )
            key_id = str(row["key_id"])
            if key_manager.current_key_id() != key_id:
                raise ApprovalVerificationError(
                    "unknown_key_id",
                    "Approval key id does not match active key.",
                )
            plan_hash = str(row["plan_hash"])
            signed_object = key_manager.signed_object(
                nonce=nonce,
                plan_hash=plan_hash,
                decisions=decisions,
            )
            signed_payload = canonical_json(signed_object)
            signature_hex = key_manager.sign_payload(signed_payload)
            conn.execute(
                """
                UPDATE approval_envelopes
                SET signed_object_json = ?, signature_hex = ?
                WHERE nonce = ? AND state = 'pending'
                """,
                (signed_payload, signature_hex, nonce),
            )

    def verify_and_consume(
        self,
        *,
        submission_json: str,
        live_scope: ApprovalScope,
        key_manager: ApprovalKeyManager,
    ) -> list[SubmittedDecision]:
        nonce, submitted_decisions = parse_submission(submission_json)
        signed_decisions = signed_decisions_from_submitted(submitted_decisions)

        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                """
                SELECT nonce, scope_json, tool_calls_json, plan_hash, key_id,
                       signed_object_json, signature_hex
                FROM approval_envelopes
                WHERE nonce = ?
                """,
                (nonce,),
            ).fetchone()
            if row is None:
                raise ApprovalVerificationError("unknown_nonce", "Approval nonce was not found.")

            verify_signature_stage(row=row, key_manager=key_manager)
            verify_signed_decisions(row=row, signed_decisions=signed_decisions)

            tool_calls = cast(list[DeferredToolCall], json.loads(str(row["tool_calls_json"])))
            stored_scope = ApprovalScope.from_dict(
                cast(dict[str, Any], json.loads(str(row["scope_json"])))
            )
            recomputed_scope = live_scope.with_tool_call_ids(stored_scope.tool_call_ids)
            recomputed_hash = compute_plan_hash(recomputed_scope, tool_calls)
            if recomputed_hash != str(row["plan_hash"]):
                raise ApprovalVerificationError(
                    "context_drift",
                    "Execution context does not match approved plan.",
                )

            verify_bijection(stored_scope.tool_call_ids, submitted_decisions)
            now = utc_now_epoch()
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
                    "expired_or_consumed",
                    "Approval nonce is expired or already consumed.",
                )
        return submitted_decisions

    def expire_pending_envelopes(self) -> None:
        with closing(self._connect()) as conn, conn:
            now = utc_now_epoch()
            conn.execute(
                """
                UPDATE approval_envelopes
                SET state = 'expired'
                WHERE state = 'pending'
                """
            )
            conn.execute(
                """
                UPDATE approval_envelopes
                SET consumed_at = ?
                WHERE state = 'expired' AND consumed_at IS NULL
                """,
                (now,),
            )

    def prune_expired_envelopes(self) -> None:
        cutoff = utc_now_epoch() - self._nonce_retention_seconds
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                DELETE FROM approval_envelopes
                WHERE state = 'expired' AND expires_at < ?
                """,
                (cutoff,),
            )

    def _connect(self) -> sqlite3.Connection:
        return open_db(self._db_path)


def _read_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer.") from exc
    if value <= 0:
        raise SystemExit(f"{name} must be > 0.")
    return value


def _read_non_negative_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer.") from exc
    if value < 0:
        raise SystemExit(f"{name} must be >= 0.")
    return value


def _resolve_approval_db_path(base_dir: Path) -> Path:
    explicit = os.getenv("APPROVAL_DB_PATH")
    if explicit:
        path = Path(explicit)
        resolved = path if path.is_absolute() else (base_dir / path)
        return resolved.resolve()
    return (base_dir / "data/approvals.sqlite").resolve()
