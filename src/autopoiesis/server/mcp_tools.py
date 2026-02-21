"""Data-layer helper functions for FastMCP server tool implementations."""

from __future__ import annotations

import json
import logging
from contextlib import closing
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from sqlite3 import Row
from typing import Any, cast

from autopoiesis.agent.runtime import Runtime
from autopoiesis.db import open_db
from autopoiesis.infra.approval.store_schema import utc_now_epoch

_LOG = logging.getLogger(__name__)

_DEFAULT_VERSION = "0.1.0"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def json_envelope(
    envelope_type: str,
    data: dict[str, Any],
    *,
    tool: str,
    meta: dict[str, Any] | None = None,
) -> str:
    envelope_meta: dict[str, Any] = {"tool": tool, "timestamp": _utc_now_iso()}
    if meta:
        envelope_meta.update(meta)
    payload = {"type": envelope_type, "data": data, "meta": envelope_meta}
    return json.dumps(payload, ensure_ascii=True, allow_nan=False)


def runtime_error_envelope(tool: str, error: RuntimeError) -> str:
    return json_envelope(
        "error.runtime_uninitialized",
        {"message": str(error)},
        tool=tool,
    )


def missing_runtime_envelope(tool: str) -> str:
    return json_envelope(
        "error.runtime_uninitialized",
        {"message": "Missing runtime."},
        tool=tool,
    )


def approval_db_path(runtime: Runtime) -> Path:
    path = getattr(runtime.approval_store, "_db_path", None)
    if isinstance(path, Path):
        return path
    raise RuntimeError("Approval store database path is unavailable.")


def parse_tool_calls(raw_value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    requests: list[dict[str, Any]] = []
    for raw_entry in cast(list[Any], parsed):
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, Any], raw_entry)
        tool_call_id = str(entry.get("tool_call_id", ""))
        tool_name = str(entry.get("tool_name", ""))
        args = entry.get("args", {})
        requests.append(
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "args": args,
            }
        )
    return requests


def _pending_rows(runtime: Runtime) -> list[Row]:
    with closing(open_db(approval_db_path(runtime))) as conn:
        return cast(
            list[Row],
            conn.execute(
                """
                SELECT envelope_id, nonce, plan_hash, tool_calls_json, issued_at, expires_at
                FROM approval_envelopes
                WHERE state = 'pending'
                ORDER BY issued_at ASC
                """
            ).fetchall(),
        )


def pending_count(runtime: Runtime) -> int:
    with closing(open_db(approval_db_path(runtime))) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS pending_count
            FROM approval_envelopes
            WHERE state = 'pending'
            """
        ).fetchone()
    return int(row["pending_count"]) if row is not None else 0


def pending_approvals(runtime: Runtime) -> list[dict[str, Any]]:
    approvals: list[dict[str, Any]] = []
    for row in _pending_rows(runtime):
        requests = parse_tool_calls(str(row["tool_calls_json"]))
        approvals.append(
            {
                "id": str(row["envelope_id"]),
                "nonce": str(row["nonce"]),
                "plan_hash_prefix": str(row["plan_hash"])[:8],
                "issued_at": int(row["issued_at"]),
                "expires_at": int(row["expires_at"]),
                "tool_count": len(requests),
                "requests": requests,
            }
        )
    return approvals


def decide_approval(
    runtime: Runtime,
    *,
    approval_id: str,
    approved: bool,
    reason: str | None,
) -> dict[str, Any] | None:
    with closing(open_db(approval_db_path(runtime))) as conn, conn:
        row = conn.execute(
            """
            SELECT envelope_id, nonce, plan_hash
            FROM approval_envelopes
            WHERE state = 'pending'
              AND (envelope_id = ? OR nonce = ?)
            """,
            (approval_id, approval_id),
        ).fetchone()
        if row is None:
            return None

        now = utc_now_epoch()
        next_state = "consumed" if approved else "expired"
        decision_record = {
            "source": "mcp.phase1",
            "approved": approved,
            "reason": reason,
            "decided_at": now,
        }
        conn.execute(
            """
            UPDATE approval_envelopes
            SET state = ?, consumed_at = ?, signed_object_json = ?
            WHERE envelope_id = ? AND state = 'pending'
            """,
            (
                next_state,
                now,
                json.dumps(decision_record, ensure_ascii=True, allow_nan=False),
                str(row["envelope_id"]),
            ),
        )
    return {
        "id": str(row["envelope_id"]),
        "nonce": str(row["nonce"]),
        "state": next_state,
        "approved": approved,
        "plan_hash_prefix": str(row["plan_hash"])[:8],
    }


def runtime_version() -> str:
    try:
        return version("autopoiesis")
    except PackageNotFoundError:
        return _DEFAULT_VERSION


def agent_config_summaries() -> list[dict[str, Any]]:
    from autopoiesis.cli import get_agent_configs

    configs = get_agent_configs()
    summaries: list[dict[str, Any]] = []
    for config in configs.values():
        summaries.append(
            {
                "name": config.name,
                "model": config.model,
                "shell_tier": config.shell_tier,
                "tools": list(config.tools),
            }
        )
    return summaries
