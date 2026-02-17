"""Tests for stream_formatting.py — tool arg/result formatting and event forwarding."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

from pydantic_ai.messages import RetryPromptPart, ToolReturnPart

from autopoiesis.display.stream_formatting import format_tool_args, format_tool_result

# -- format_tool_args --------------------------------------------------------


def test_format_tool_args_none() -> None:
    assert format_tool_args(None) is None


def test_format_tool_args_empty_string() -> None:
    assert format_tool_args("") is None
    assert format_tool_args("   ") is None


def test_format_tool_args_plain_string() -> None:
    assert format_tool_args("not json") == "not json"


def test_format_tool_args_json_string() -> None:
    result = format_tool_args('{"b": 2, "a": 1}')
    assert result is not None
    assert '"a": 1' in result
    assert '"b": 2' in result


def test_format_tool_args_empty_dict() -> None:
    assert format_tool_args({}) is None


def test_format_tool_args_dict() -> None:
    result = format_tool_args({"key": "val"})
    assert result is not None
    assert '"key"' in result


# -- format_tool_result ------------------------------------------------------


def test_format_tool_result_retry() -> None:
    part = RetryPromptPart(content="try again")
    status, details = format_tool_result(part)
    assert status == "error"
    assert details == "try again"


def test_format_tool_result_success_string() -> None:
    part = ToolReturnPart(tool_name="t", content="ok", tool_call_id="x")
    status, details = format_tool_result(part)
    assert status == "done"
    assert details == "ok"


def test_format_tool_result_success_empty() -> None:
    part = ToolReturnPart(tool_name="t", content="", tool_call_id="x")
    status, details = format_tool_result(part)
    assert status == "done"
    assert details is None


# -- forward_stream_events (drain path) -------------------------------------


def test_forward_drain_non_tool_handle() -> None:
    """Non-ToolAwareStreamHandle should just drain the iterator."""
    from collections.abc import AsyncIterator

    from pydantic_ai.messages import AgentStreamEvent

    from autopoiesis.display.stream_formatting import forward_stream_events

    class PlainHandle:
        def write(self, chunk: str) -> None:
            pass

        def close(self) -> None:
            pass

    async def _events() -> AsyncIterator[AgentStreamEvent]:
        return
        yield  # make it an async generator

    ctx: Any = MagicMock()

    asyncio.run(forward_stream_events(PlainHandle(), ctx, _events()))
