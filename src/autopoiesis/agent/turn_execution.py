"""Bounded turn execution helpers for worker runtime guardrails."""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import AsyncIterable
from dataclasses import dataclass
from typing import Any

from pydantic_ai import DeferredToolRequests
from pydantic_ai.exceptions import UsageLimitExceeded, UserError
from pydantic_ai.messages import AgentStreamEvent, ModelMessage
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import DeferredToolResults, RunContext
from pydantic_ai.usage import RunUsage, UsageLimits

from autopoiesis.agent.loop_guards import resolve_loop_guards, warning_threshold, warning_timeout
from autopoiesis.agent.runtime import Runtime
from autopoiesis.display.stream_formatting import forward_stream_events
from autopoiesis.display.streaming import StreamHandle, ToolAwareStreamHandle
from autopoiesis.models import AgentDeps

_log = logging.getLogger(__name__)

# Minimum timeout to prevent zero or negative values
MIN_TIMEOUT_SECONDS = 0.1

AgentOutput = str | DeferredToolRequests


@dataclass(frozen=True)
class TurnExecution:
    """Turn output and full message history."""

    output: AgentOutput
    messages: list[ModelMessage]


@dataclass(frozen=True)
class TurnExecutionParams:
    """Parameters for turn execution."""

    work_item_id: str
    prompt: str | None
    deps: AgentDeps
    history: list[ModelMessage]
    deferred_results: DeferredToolResults | None
    stream_handle: StreamHandle | None


class WorkItemLimitExceededError(RuntimeError):
    """Raised when a per-work-item safety limit is reached."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.user_message = message


def run_turn(
    rt: Runtime,
    params: TurnExecutionParams,
) -> TurnExecution:
    """Execute one turn with iteration, token, and wall-clock guards."""
    guards = resolve_loop_guards(rt)
    usage = RunUsage()
    started_at = time.monotonic()
    warned_timeout = False
    warning_seconds = warning_timeout(guards.work_item_timeout_seconds)
    output_type: list[type[AgentOutput]] = [str, DeferredToolRequests]

    def check_timeout() -> None:
        nonlocal warned_timeout
        elapsed = time.monotonic() - started_at
        if not warned_timeout and elapsed >= warning_seconds:
            _log.warning(
                "Work item %s reached 80%% of wall-clock timeout (%.1fs/%.1fs).",
                params.work_item_id,
                elapsed,
                guards.work_item_timeout_seconds,
            )
            warned_timeout = True
        if elapsed >= guards.work_item_timeout_seconds:
            raise WorkItemLimitExceededError(
                "Partial result: work item exceeded wall-clock timeout and was stopped."
            )

    usage_limits = UsageLimits(
        tool_calls_limit=guards.tool_loop_max_iterations,
        total_tokens_limit=guards.work_item_token_budget,
    )
    run_kwargs: dict[str, object] = {
        "deps": params.deps,
        "message_history": params.history,
        "output_type": output_type,
        "deferred_tool_results": params.deferred_results,
        "usage": usage,
        "usage_limits": usage_limits,
        "model_settings": _timeout_model_settings(guards.work_item_timeout_seconds),
    }

    try:
        check_timeout()
        if params.stream_handle is None:
            run_kwargs["event_stream_handler"] = _noop_event_handler(check_timeout)
            result = _invoke(
                rt.agent.run_sync,
                params.prompt,
                run_kwargs,
            )
            check_timeout()
            _warn_usage_thresholds(
                params.work_item_id, guards.tool_loop_max_iterations, usage.tool_calls, "tool"
            )
            _warn_usage_thresholds(
                params.work_item_id,
                guards.work_item_token_budget,
                usage.total_tokens,
                "token",
            )
            return TurnExecution(output=result.output, messages=result.all_messages())
        run_kwargs["event_stream_handler"] = _forwarding_event_handler(
            stream_handle=params.stream_handle,
            check_timeout=check_timeout,
        )
        stream = _invoke(rt.agent.run_stream_sync, params.prompt, run_kwargs)
        try:
            for chunk in stream.stream_text(delta=True):
                check_timeout()
                params.stream_handle.write(chunk)
        except UserError:
            _log.debug("stream_text unavailable (non-text output); skipping")
        if isinstance(params.stream_handle, ToolAwareStreamHandle):
            params.stream_handle.finish_thinking()
        check_timeout()
        _warn_usage_thresholds(
            params.work_item_id, guards.tool_loop_max_iterations, usage.tool_calls, "tool"
        )
        _warn_usage_thresholds(
            params.work_item_id, guards.work_item_token_budget, usage.total_tokens, "token"
        )
        return TurnExecution(output=stream.get_output(), messages=stream.all_messages())
    except UsageLimitExceeded as exc:
        _warn_usage_thresholds(
            params.work_item_id, guards.tool_loop_max_iterations, usage.tool_calls, "tool"
        )
        _warn_usage_thresholds(
            params.work_item_id, guards.work_item_token_budget, usage.total_tokens, "token"
        )
        raise WorkItemLimitExceededError(usage_limit_message(exc)) from exc
    finally:
        if params.stream_handle is not None:
            params.stream_handle.close()


def usage_limit_message(error: UsageLimitExceeded) -> str:
    """Convert UsageLimitExceeded into a user-facing partial-result message."""
    message = str(error)
    if "tool_calls_limit" in message:
        return "Partial result: tool loop iteration cap reached and execution was stopped."
    if "total_tokens_limit" in message:
        return "Partial result: work item token budget reached and execution was stopped."
    return f"Partial result: usage limit reached and execution was stopped ({message})."


def _warn_usage_thresholds(work_item_id: str, limit: int, value: int, label: str) -> None:
    """Log a warning once usage reaches 80% of the configured budget."""
    if value < warning_threshold(limit):
        return
    unit = "calls" if label == "tool" else "tokens"
    _log.warning(
        "Work item %s reached 80%% of %s limit (%d/%d %s).",
        work_item_id,
        label,
        value,
        limit,
        unit,
    )


def _invoke(method: Any, prompt: str | None, run_kwargs: dict[str, object]) -> Any:
    """Call an agent run method while tolerating narrower fake-agent signatures in tests."""
    signature = inspect.signature(method)
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_kwargs:
        return method(prompt, **run_kwargs)
    filtered = {k: v for k, v in run_kwargs.items() if k in signature.parameters}
    return method(prompt, **filtered)


def _timeout_model_settings(timeout_seconds: float) -> ModelSettings:
    """Build per-request timeout settings from work-item timeout budget."""
    timeout = timeout_seconds if timeout_seconds > MIN_TIMEOUT_SECONDS else MIN_TIMEOUT_SECONDS
    return {"timeout": timeout}


def _forwarding_event_handler(
    *,
    stream_handle: StreamHandle,
    check_timeout: Any,
) -> Any:
    """Build event handler that forwards stream events and enforces timeout."""

    async def _on_events(
        ctx: RunContext[AgentDeps],
        events: AsyncIterable[AgentStreamEvent],
    ) -> None:
        async def _checked() -> AsyncIterable[AgentStreamEvent]:
            async for event in events:
                check_timeout()
                yield event

        await forward_stream_events(stream_handle, ctx, _checked())

    return _on_events


def _noop_event_handler(check_timeout: Any) -> Any:
    """Build event handler that just enforces timeout checks in non-streaming mode."""

    async def _on_events(
        _ctx: RunContext[AgentDeps],
        events: AsyncIterable[AgentStreamEvent],
    ) -> None:
        async for _ in events:
            check_timeout()

    return _on_events
