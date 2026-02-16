"""Stream event formatting and forwarding helpers.

Extracts tool-call argument formatting, result summarisation, and the
event-routing coroutine so that ``chat_worker`` stays under the line limit.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterable
from typing import Any

from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    ThinkingPart,
    ThinkingPartDelta,
    ToolReturnPart,
)
from pydantic_ai.tools import RunContext

from display.streaming import ChannelStatus, StreamHandle, ToolAwareStreamHandle
from models import AgentDeps

_log = logging.getLogger(__name__)


def format_tool_args(args: str | dict[str, Any] | None) -> str | None:
    """Format tool call arguments for display."""
    if args is None:
        return None
    if isinstance(args, str):
        stripped = args.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
        return json.dumps(parsed, indent=2, sort_keys=True, default=str)
    if not args:
        return None
    return json.dumps(args, indent=2, sort_keys=True, default=str)


def format_tool_result(
    result: ToolReturnPart | RetryPromptPart,
) -> tuple[ChannelStatus, str | None]:
    """Extract status and summary from a tool result part."""
    if isinstance(result, RetryPromptPart):
        content = result.content
        details = content if isinstance(content, str) else json.dumps(content, default=str)
        return "error", details or None
    content = result.content
    details = content if isinstance(content, str) else json.dumps(content, default=str)
    return "done", details or None


async def forward_stream_events(
    handle: StreamHandle,
    _ctx: RunContext[AgentDeps],
    events: AsyncIterable[AgentStreamEvent],
) -> None:
    """Route tool and thinking events to a *ToolAwareStreamHandle*.

    If *handle* does not support tool-aware callbacks the event iterable is
    drained so the stream does not stall (pydantic-ai requires the async
    iterator to be fully consumed).
    """
    if not isinstance(handle, ToolAwareStreamHandle):
        # Drain the async iterator to avoid a stalled stream.
        drained_events = 0
        async for _ in events:
            drained_events += 1
        _log.debug(
            "Dropped %d stream event(s): %s does not implement ToolAwareStreamHandle",
            drained_events,
            type(handle).__name__,
        )
        return

    async for event in events:
        if isinstance(event, FunctionToolCallEvent):
            details = format_tool_args(event.part.args)
            handle.start_tool_call(event.tool_call_id, event.part.tool_name, details)
        elif isinstance(event, FunctionToolResultEvent):
            status, details = format_tool_result(event.result)
            handle.finish_tool_call(event.tool_call_id, status, details)
        elif isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart):
            handle.start_thinking()
            if event.part.content:
                handle.update_thinking(event.part.content)
        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, ThinkingPartDelta):
            if event.delta.content_delta:
                handle.update_thinking(event.delta.content_delta)
