"""FastMCP server exposing runtime controls over streamable HTTP."""

from __future__ import annotations

import inspect
import json
import logging
import time
from contextlib import closing
from datetime import UTC, datetime
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from sqlite3 import Row
from typing import Any, cast

from autopoiesis.agent.runtime import Runtime, get_runtime
from autopoiesis.db import open_db
from autopoiesis.infra.approval.store_schema import utc_now_epoch

_LOG = logging.getLogger(__name__)

_DEFAULT_VERSION = "0.1.0"
_SERVER_STARTED_AT = time.monotonic()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_envelope(
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


def _runtime_error(tool: str, error: RuntimeError) -> str:
    return _json_envelope(
        "error.runtime_uninitialized",
        {"message": str(error)},
        tool=tool,
    )


def _missing_runtime_envelope(tool: str) -> str:
    return _json_envelope(
        "error.runtime_uninitialized",
        {"message": "Missing runtime."},
        tool=tool,
    )


def _runtime_for_tool(tool: str) -> tuple[Runtime | None, str | None]:
    try:
        return get_runtime(), None
    except RuntimeError as exc:
        return None, _runtime_error(tool, exc)


def _approval_db_path(runtime: Runtime) -> Path:
    path = getattr(runtime.approval_store, "_db_path", None)
    if isinstance(path, Path):
        return path
    raise RuntimeError("Approval store database path is unavailable.")


def _parse_tool_calls(raw_value: str) -> list[dict[str, Any]]:
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
    with closing(open_db(_approval_db_path(runtime))) as conn:
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


def _pending_count(runtime: Runtime) -> int:
    with closing(open_db(_approval_db_path(runtime))) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS pending_count
            FROM approval_envelopes
            WHERE state = 'pending'
            """
        ).fetchone()
    return int(row["pending_count"]) if row is not None else 0


def _pending_approvals(runtime: Runtime) -> list[dict[str, Any]]:
    approvals: list[dict[str, Any]] = []
    for row in _pending_rows(runtime):
        requests = _parse_tool_calls(str(row["tool_calls_json"]))
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


def _decide_approval(
    runtime: Runtime,
    *,
    approval_id: str,
    approved: bool,
    reason: str | None,
) -> dict[str, Any] | None:
    with closing(open_db(_approval_db_path(runtime))) as conn, conn:
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


def _runtime_version() -> str:
    try:
        return version("autopoiesis")
    except PackageNotFoundError:
        return _DEFAULT_VERSION


def _agent_config_summaries() -> list[dict[str, Any]]:
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


async def _emit_approval_state_notification() -> bool:
    if mcp is None:
        return False
    notify = getattr(mcp, "notify_tool_list_changed", None)
    if notify is None:
        return False

    try:
        result = notify()
        if inspect.isawaitable(result):
            await result
        return True
    except Exception:
        _LOG.exception("Failed to emit approval state notification")
        return False


def dashboard_status() -> str:
    """Return runtime health and pending approval count."""
    runtime, error = _runtime_for_tool("dashboard.status")
    if error is not None:
        return error
    if runtime is None:
        return _missing_runtime_envelope("dashboard.status")

    data = {
        "initialized": True,
        "agent_name": runtime.agent_name,
        "shell_tier": runtime.shell_tier,
        "approval_unlocked": runtime.approval_unlocked,
        "pending_approvals_count": _pending_count(runtime),
    }
    return _json_envelope("dashboard.status", data, tool="dashboard.status")


def approval_list() -> str:
    """Return pending approval envelopes."""
    runtime, error = _runtime_for_tool("approval.list")
    if error is not None:
        return error
    if runtime is None:
        return _missing_runtime_envelope("approval.list")

    pending = _pending_approvals(runtime)
    data = {"count": len(pending), "items": pending}
    return _json_envelope("approval.list", data, tool="approval.list")


async def approval_decide(approval_id: str, approved: bool, reason: str | None = None) -> str:
    """Approve or reject a pending approval envelope by id or nonce."""
    runtime, error = _runtime_for_tool("approval.decide")
    if error is not None:
        return error
    if runtime is None:
        return _missing_runtime_envelope("approval.decide")

    decision = _decide_approval(runtime, approval_id=approval_id, approved=approved, reason=reason)
    if decision is None:
        return _json_envelope(
            "error.approval_not_found",
            {"approval_id": approval_id},
            tool="approval.decide",
        )

    emitted = await _emit_approval_state_notification()
    return _json_envelope(
        "approval.decision",
        decision,
        tool="approval.decide",
        meta={"notification_emitted": emitted},
    )


def system_info() -> str:
    """Return runtime version, uptime, and loaded agent config summaries."""
    runtime, error = _runtime_for_tool("system.info")
    if error is not None:
        return error
    if runtime is None:
        return _missing_runtime_envelope("system.info")

    uptime_seconds = int(time.monotonic() - _SERVER_STARTED_AT)
    data = {
        "version": _runtime_version(),
        "uptime_seconds": uptime_seconds,
        "agent_name": runtime.agent_name,
        "agent_configs": _agent_config_summaries(),
    }
    return _json_envelope("system.info", data, tool="system.info")


def _load_fastmcp_class() -> type[Any] | None:
    try:
        module = import_module("fastmcp")
    except ModuleNotFoundError:
        _LOG.warning("fastmcp is not installed. Run `uv sync` to enable /mcp.")
        return None

    fastmcp_class = getattr(module, "FastMCP", None)
    if not isinstance(fastmcp_class, type):
        _LOG.error("fastmcp.FastMCP is unavailable. /mcp endpoint disabled.")
        return None
    return cast(type[Any], fastmcp_class)


def _register_tools(server: Any) -> None:
    server.tool(name="dashboard.status")(dashboard_status)
    server.tool(name="approval.list")(approval_list)
    server.tool(name="approval.decide")(approval_decide)
    server.tool(name="system.info")(system_info)


def create_mcp_server(fastmcp_class: type[Any] | None = None) -> Any | None:
    """Create and register the MCP server instance."""
    server_class = fastmcp_class if fastmcp_class is not None else _load_fastmcp_class()
    if server_class is None:
        return None
    server = server_class("autopoiesis")
    _register_tools(server)
    return server


mcp = create_mcp_server()
