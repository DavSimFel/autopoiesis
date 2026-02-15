"""SQLite approval envelope storage and verification workflow."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from approval_keys import ApprovalKeyManager
from approval_types import (
    SIGNED_OBJECT_CONTEXT,
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
        self._init_schema()

    @classmethod
    def from_env(cls, *, base_dir: Path) -> ApprovalStore:
        ttl = _read_positive_int("APPROVAL_TTL_SECONDS", _DEFAULT_APPROVAL_TTL_SECONDS)
        retention = _read_positive_int(
            "NONCE_RETENTION_PERIOD_SECONDS", _DEFAULT_NONCE_RETENTION_SECONDS
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
        self, *, scope: ApprovalScope, tool_calls: list[DeferredToolCall], key_id: str
    ) -> tuple[str, str]:
        issued_at = _utc_now_epoch()
        expires_at = issued_at + self._ttl_seconds
        nonce = uuid4().hex
        envelope_id = str(uuid4())
        tool_call_ids = [call["tool_call_id"] for call in tool_calls]
        scoped = scope.with_tool_call_ids(tool_call_ids)
        plan_hash = compute_plan_hash(scoped, tool_calls)
        with self._connect() as conn:
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
        with self._connect() as conn:
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
                    "expired_or_consumed", "Approval nonce is already consumed or expired."
                )
            key_id = str(row["key_id"])
            if key_manager.current_key_id() != key_id:
                raise ApprovalVerificationError(
                    "unknown_key_id", "Approval key id does not match active key."
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
        submission = self._parse_submission(submission_json)
        nonce = submission["nonce"]
        submitted_decisions = submission["decisions"]
        signed_decisions = signed_decisions_from_submitted(submitted_decisions)

        with self._connect() as conn:
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
            self._verify_signature_stage(row=row, key_manager=key_manager)
            tool_calls = cast(
                list[DeferredToolCall], json.loads(str(row["tool_calls_json"]))
            )
            stored_scope = ApprovalScope.from_dict(
                cast(dict[str, Any], json.loads(str(row["scope_json"])))
            )
            self._verify_signed_decisions(row=row, signed_decisions=signed_decisions)
            recomputed_scope = live_scope.with_tool_call_ids(stored_scope.tool_call_ids)
            recomputed_hash = compute_plan_hash(recomputed_scope, tool_calls)
            if recomputed_hash != str(row["plan_hash"]):
                raise ApprovalVerificationError(
                    "context_drift", "Execution context does not match approved plan."
                )
            self._verify_bijection(stored_scope.tool_call_ids, submitted_decisions)
            now = _utc_now_epoch()
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
        return submitted_decisions

    def expire_pending_envelopes(self) -> None:
        with self._connect() as conn:
            now = _utc_now_epoch()
            conn.execute(
                """
                UPDATE approval_envelopes
                SET state = 'expired'
                WHERE state = 'pending'
                """,
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
        cutoff = _utc_now_epoch() - self._nonce_retention_seconds
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM approval_envelopes
                WHERE state = 'expired' AND expires_at < ?
                """,
                (cutoff,),
            )

    def _verify_signature_stage(
        self, *, row: sqlite3.Row, key_manager: ApprovalKeyManager
    ) -> None:
        key_id = str(row["key_id"])
        signed_payload = row["signed_object_json"]
        signature_hex = row["signature_hex"]
        if not key_id:
            raise ApprovalVerificationError(
                "unknown_key_id", "Approval envelope key id is missing."
            )
        if not isinstance(signed_payload, str) or not signed_payload:
            raise ApprovalVerificationError(
                "invalid_signature", "Approval signature payload is missing."
            )
        if not isinstance(signature_hex, str) or not signature_hex:
            raise ApprovalVerificationError("invalid_signature", "Approval signature is missing.")
        if key_manager.resolve_public_key(key_id) is None:
            raise ApprovalVerificationError("unknown_key_id", "Verification key not found.")
        if not key_manager.verify_signature(key_id, signed_payload, signature_hex):
            raise ApprovalVerificationError(
                "invalid_signature", "Approval signature verification failed."
            )

    def _verify_signed_decisions(
        self, *, row: sqlite3.Row, signed_decisions: list[SignedDecision]
    ) -> None:
        signed_payload = row["signed_object_json"]
        if not isinstance(signed_payload, str):
            raise ApprovalVerificationError("invalid_signature", "Signed payload missing.")
        try:
            loaded = json.loads(signed_payload)
        except json.JSONDecodeError as exc:
            raise ApprovalVerificationError(
                "invalid_signature", "Signed payload JSON is invalid."
            ) from exc
        if not isinstance(loaded, dict):
            raise ApprovalVerificationError("invalid_signature", "Signed payload shape is invalid.")
        signed_object = cast(dict[str, Any], loaded)
        if signed_object.get("ctx") != SIGNED_OBJECT_CONTEXT:
            raise ApprovalVerificationError(
                "invalid_signature", "Signed payload context is invalid."
            )
        if signed_object.get("nonce") != str(row["nonce"]):
            raise ApprovalVerificationError("invalid_signature", "Signed payload nonce mismatch.")
        if signed_object.get("plan_hash") != str(row["plan_hash"]):
            raise ApprovalVerificationError(
                "invalid_signature", "Signed payload plan_hash mismatch."
            )
        if signed_object.get("key_id") != str(row["key_id"]):
            raise ApprovalVerificationError("invalid_signature", "Signed payload key_id mismatch.")
        signed_payload_decisions = signed_object.get("decisions")
        if not isinstance(signed_payload_decisions, list):
            raise ApprovalVerificationError(
                "invalid_signature", "Signed payload decisions are invalid."
            )
        if signed_payload_decisions != signed_decisions:
            raise ApprovalVerificationError(
                "bijection_mismatch", "Submitted approvals do not match signed decisions."
            )

    def _verify_bijection(
        self, tool_call_ids: list[str], submitted_decisions: list[SubmittedDecision]
    ) -> None:
        submitted_ids = [item["tool_call_id"] for item in submitted_decisions]
        if submitted_ids != tool_call_ids:
            raise ApprovalVerificationError(
                "bijection_mismatch", "Approval decisions do not match requested tool calls."
            )

    def _parse_submission(self, submission_json: str) -> dict[str, Any]:
        try:
            loaded = json.loads(submission_json)
        except json.JSONDecodeError as exc:
            raise ApprovalVerificationError(
                "invalid_submission", "Approval submission is not valid JSON."
            ) from exc
        if not isinstance(loaded, dict):
            raise ApprovalVerificationError(
                "invalid_submission", "Approval submission must be a JSON object."
            )
        payload = cast(dict[str, Any], loaded)
        nonce = payload.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            raise ApprovalVerificationError(
                "invalid_submission", "Approval submission nonce is missing."
            )
        decisions = payload.get("decisions")
        if not isinstance(decisions, list):
            raise ApprovalVerificationError(
                "invalid_submission", "Approval submission decisions are missing."
            )
        decision_items = cast(list[Any], decisions)
        normalized = [self._validate_submitted_decision(item) for item in decision_items]
        return {"nonce": nonce, "decisions": normalized}

    def _validate_submitted_decision(self, raw: Any) -> SubmittedDecision:
        if not isinstance(raw, dict):
            raise ApprovalVerificationError(
                "invalid_submission", "Approval decision entry must be an object."
            )
        item = cast(dict[str, Any], raw)
        tool_call_id = item.get("tool_call_id")
        approved = item.get("approved")
        denial_message = item.get("denial_message")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise ApprovalVerificationError(
                "invalid_submission", "Approval decision tool_call_id is invalid."
            )
        if not isinstance(approved, bool):
            raise ApprovalVerificationError(
                "invalid_submission", "Approval decision approved must be boolean."
            )
        if denial_message is not None and not isinstance(denial_message, str):
            raise ApprovalVerificationError(
                "invalid_submission", "Approval decision denial_message must be string or null."
            )
        return {
            "tool_call_id": tool_call_id,
            "approved": approved,
            "denial_message": denial_message,
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            if not _table_exists(conn, "approval_envelopes"):
                self._create_schema(conn)
                return
            if _schema_is_current(conn):
                return
            self._migrate_legacy_schema(conn)

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE approval_envelopes (
                envelope_id TEXT PRIMARY KEY,
                nonce TEXT UNIQUE NOT NULL,
                scope_json TEXT NOT NULL,
                tool_calls_json TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                key_id TEXT NOT NULL,
                signed_object_json TEXT,
                signature_hex TEXT,
                state TEXT NOT NULL,
                issued_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER
            )
            """
        )

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE approval_envelopes RENAME TO approval_envelopes_legacy")
        self._create_schema(conn)
        now = _utc_now_epoch()
        rows = conn.execute(
            """
            SELECT nonce, scope_json, tool_calls_json, plan_hash, state,
                   issued_at, expires_at, consumed_at
            FROM approval_envelopes_legacy
            """
        ).fetchall()
        for row in rows:
            state = str(row["state"])
            migrated_state = "expired" if state == "pending" else state
            migrated_consumed_at = (
                now
                if state == "pending"
                else int(row["consumed_at"]) if row["consumed_at"] is not None else None
            )
            conn.execute(
                """
                INSERT INTO approval_envelopes (
                    envelope_id, nonce, scope_json, tool_calls_json, plan_hash, key_id,
                    signed_object_json, signature_hex, state, issued_at, expires_at, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    str(row["nonce"]),
                    str(row["scope_json"]),
                    str(row["tool_calls_json"]),
                    str(row["plan_hash"]),
                    "",
                    migrated_state,
                    int(row["issued_at"]),
                    int(row["expires_at"]),
                    migrated_consumed_at,
                ),
            )
        conn.execute("DROP TABLE approval_envelopes_legacy")


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
    db_url = os.getenv("DBOS_SYSTEM_DATABASE_URL", "sqlite:///dbostest.sqlite")
    if db_url.startswith("sqlite:///"):
        return Path(db_url.removeprefix("sqlite:///")).resolve()
    raise SystemExit(
        "Approval store requires SQLite. Set APPROVAL_DB_PATH "
        "or use sqlite:/// DBOS_SYSTEM_DATABASE_URL."
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table_name,)
    ).fetchone()
    return row is not None


def _schema_is_current(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA table_info(approval_envelopes)").fetchall()
    columns = {str(row[1]) for row in rows}
    expected = {
        "envelope_id",
        "nonce",
        "scope_json",
        "tool_calls_json",
        "plan_hash",
        "key_id",
        "signed_object_json",
        "signature_hex",
        "state",
        "issued_at",
        "expires_at",
        "consumed_at",
    }
    return columns == expected


def _utc_now_epoch() -> int:
    return int(datetime.now(UTC).timestamp())
