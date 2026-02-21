"""FastMCP server exposing runtime controls over streamable HTTP."""

from __future__ import annotations

import inspect
import logging
import time
from importlib import import_module
from typing import Any, cast

from autopoiesis.agent.runtime import Runtime, get_runtime
from autopoiesis.server.mcp_tools import (
    agent_config_summaries,
    decide_approval,
    json_envelope,
    missing_runtime_envelope,
    pending_approvals,
    pending_count,
    runtime_error_envelope,
    runtime_version,
)

_LOG = logging.getLogger(__name__)

_SERVER_STARTED_AT = time.monotonic()


def _runtime_for_tool(tool: str) -> tuple[Runtime | None, str | None]:
    try:
        return get_runtime(), None
    except RuntimeError as exc:
        return None, runtime_error_envelope(tool, exc)


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
        return missing_runtime_envelope("dashboard.status")

    data = {
        "initialized": True,
        "agent_name": runtime.agent_name,
        "shell_tier": runtime.shell_tier,
        "approval_unlocked": runtime.approval_unlocked,
        "pending_approvals_count": pending_count(runtime),
    }
    return json_envelope("dashboard.status", data, tool="dashboard.status")


def approval_list() -> str:
    """Return pending approval envelopes."""
    runtime, error = _runtime_for_tool("approval.list")
    if error is not None:
        return error
    if runtime is None:
        return missing_runtime_envelope("approval.list")

    pending = pending_approvals(runtime)
    data = {"count": len(pending), "items": pending}
    return json_envelope("approval.list", data, tool="approval.list")


async def approval_decide(approval_id: str, approved: bool, reason: str | None = None) -> str:
    """Approve or reject a pending approval envelope by id or nonce."""
    runtime, error = _runtime_for_tool("approval.decide")
    if error is not None:
        return error
    if runtime is None:
        return missing_runtime_envelope("approval.decide")

    decision = decide_approval(runtime, approval_id=approval_id, approved=approved, reason=reason)
    if decision is None:
        return json_envelope(
            "error.approval_not_found",
            {"approval_id": approval_id},
            tool="approval.decide",
        )

    emitted = await _emit_approval_state_notification()
    return json_envelope(
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
        return missing_runtime_envelope("system.info")

    uptime_seconds = int(time.monotonic() - _SERVER_STARTED_AT)
    data = {
        "version": runtime_version(),
        "uptime_seconds": uptime_seconds,
        "agent_name": runtime.agent_name,
        "agent_configs": agent_config_summaries(),
    }
    return json_envelope("system.info", data, tool="system.info")


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
