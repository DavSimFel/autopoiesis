"""Tests for ApprovalGateTransform."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP
from fastmcp.tools import tool

from autopoiesis.skills.auth_middleware import ApprovalGateTransform


def _tool_text(result: object) -> str:
    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return text
    return str(result)


def _build_server(unlocked: bool) -> FastMCP:
    @tool(meta={"approval_tier": "approve"})
    def dangerous() -> str:
        """Dangerous operation."""
        return "executed"

    @tool
    def safe() -> str:
        """Safe operation."""
        return "safe"

    server = FastMCP("approval-gate")
    server.add_tool(dangerous)
    server.add_tool(safe)
    server.add_transform(ApprovalGateTransform(unlock_check=lambda: unlocked))
    return server


def test_approval_gate_blocks_without_unlock() -> None:
    server = _build_server(unlocked=False)

    dangerous = asyncio.run(server.call_tool("dangerous", {}))
    safe = asyncio.run(server.call_tool("safe", {}))

    assert "Approval required" in _tool_text(dangerous)
    assert _tool_text(safe) == "safe"


def test_approval_gate_allows_when_unlocked() -> None:
    server = _build_server(unlocked=True)

    dangerous = asyncio.run(server.call_tool("dangerous", {}))

    assert _tool_text(dangerous) == "executed"
