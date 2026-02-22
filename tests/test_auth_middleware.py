"""Tests for ApprovalGateTransform."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP

from autopoiesis.skills.auth_middleware import ApprovalGateTransform


def _tool_text(result: object) -> str:
    from fastmcp.tools.tool import ToolResult

    if not isinstance(result, ToolResult):
        return str(result)
    content = result.content
    if isinstance(content, str):
        return content
    if len(content) > 0:
        first = content[0]
        text: object = getattr(first, "text", None)
        if isinstance(text, str):
            return text
    return str(content)


def _build_server(*, unlocked: bool) -> FastMCP:
    server = FastMCP("approval-gate")

    @server.tool(meta={"approval_tier": "approve"})
    def dangerous() -> str:
        """Dangerous operation."""
        return "executed"

    _ = dangerous  # registered via decorator

    @server.tool()
    def safe() -> str:
        """Safe operation."""
        return "safe"

    _ = safe  # registered via decorator

    server.add_transform(ApprovalGateTransform(unlock_check=lambda: unlocked))
    return server


def test_approval_gate_blocks_without_unlock() -> None:
    server = _build_server(unlocked=False)

    dangerous_result = asyncio.run(server.call_tool("dangerous", {}))
    safe_result = asyncio.run(server.call_tool("safe", {}))

    assert "Approval required" in _tool_text(dangerous_result)
    assert _tool_text(safe_result) == "safe"


def test_approval_gate_allows_when_unlocked() -> None:
    server = _build_server(unlocked=True)

    dangerous_result = asyncio.run(server.call_tool("dangerous", {}))

    assert _tool_text(dangerous_result) == "executed"
