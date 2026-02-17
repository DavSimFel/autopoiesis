"""Tests for the run_simple convenience wrapper."""

from __future__ import annotations

import pytest
from pydantic_ai import Agent, FunctionToolset, Tool

from autopoiesis.models import AgentDeps
from autopoiesis.run_simple import SimpleResult, run_simple

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORKSPACE_SENTINEL = "/tmp/test-run-simple-workspace"


def _make_deps() -> AgentDeps:
    from pydantic_ai_backends import LocalBackend

    return AgentDeps(backend=LocalBackend(root_dir=_WORKSPACE_SENTINEL, enable_execute=False))


def _echo_tool(text: str) -> str:
    """Echo the input text back."""
    return f"echo:{text}"


def _build_agent_with_approval() -> Agent[AgentDeps, str]:
    """Build a test agent with a tool requiring approval."""
    ts: FunctionToolset[AgentDeps] = FunctionToolset(
        tools=[Tool(_echo_tool, requires_approval=True)]
    )
    return Agent("test", deps_type=AgentDeps, toolsets=[ts])


def _build_agent_no_approval() -> Agent[AgentDeps, str]:
    """Build a test agent with no approval-required tools."""
    ts: FunctionToolset[AgentDeps] = FunctionToolset(tools=[Tool(_echo_tool)])
    return Agent("test", deps_type=AgentDeps, toolsets=[ts])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunSimpleApprovalFlow:
    """Verify run_simple auto-approves deferred tool requests."""

    def test_auto_approves_deferred_tools(self) -> None:
        agent = _build_agent_with_approval()
        result = run_simple(agent, "hello", _make_deps())

        assert isinstance(result, SimpleResult)
        assert isinstance(result.text, str)
        assert result.approval_rounds >= 1
        assert len(result.all_messages) > 0

    def test_no_approval_needed(self) -> None:
        agent = _build_agent_no_approval()
        result = run_simple(agent, "hello", _make_deps())

        assert isinstance(result.text, str)
        assert result.approval_rounds == 0

    def test_max_rounds_exceeded_raises(self) -> None:
        """An agent that always defers should raise after max_rounds."""
        # With max_rounds=0 we should immediately raise
        agent = _build_agent_with_approval()
        with pytest.raises(RuntimeError, match="did not produce a text response"):
            run_simple(agent, "hello", _make_deps(), max_rounds=0)

    def test_message_history_passed_through(self) -> None:
        agent = _build_agent_no_approval()
        result1 = run_simple(agent, "first", _make_deps())
        result2 = run_simple(agent, "second", _make_deps(), message_history=result1.all_messages)

        assert isinstance(result2.text, str)
        assert len(result2.all_messages) > len(result1.all_messages)
