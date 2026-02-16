"""DBOS worker and queue helpers for chat work items."""

from __future__ import annotations

import asyncio
import os
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.tools import DeferredToolResults

from approval_types import ApprovalScope
from chat_approval import (
    build_approval_scope,
    deserialize_deferred_results,
    serialize_deferred_requests,
)
from chat_runtime import Runtime, get_runtime
from history_store import clear_checkpoint, load_checkpoint, save_checkpoint
from models import AgentDeps, WorkItem, WorkItemOutput
from streaming import StreamHandle, take_stream
from work_queue import work_queue

try:
    from dbos import DBOS, SetEnqueueOptions
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing DBOS dependencies. Run `uv sync` so "
        "`pydantic-ai-slim[dbos,mcp]` and `dbos` are installed."
    ) from exc


AgentOutput = str | DeferredToolRequests


@dataclass(frozen=True)
class _CheckpointContext:
    """Per-run checkpoint metadata used by history processors."""

    db_path: str
    work_item_id: str


_active_checkpoint_context: ContextVar[_CheckpointContext | None] = ContextVar(
    "active_checkpoint_context",
    default=None,
)


@dataclass(frozen=True)
class _TurnInput:
    """Bundled arguments for a single agent turn."""

    prompt: str | None
    deps: AgentDeps
    history: list[ModelMessage]
    deferred_results: DeferredToolResults | None
    scope: ApprovalScope


def _deserialize_history(history_json: str | None) -> list[ModelMessage]:
    if not history_json:
        return []
    return ModelMessagesTypeAdapter.validate_json(history_json)


def _serialize_history(messages: list[ModelMessage]) -> str:
    return ModelMessagesTypeAdapter.dump_json(messages).decode()


def _count_history_rounds(messages: list[ModelMessage]) -> int:
    """Count completed model rounds from serialized message history."""
    model_responses = sum(1 for message in messages if isinstance(message, ModelResponse))
    return model_responses if model_responses > 0 else len(messages)


def checkpoint_history_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Persist an in-flight checkpoint whenever the active work item updates history."""
    checkpoint = _active_checkpoint_context.get()
    if checkpoint is None:
        return messages
    save_checkpoint(
        db_path=checkpoint.db_path,
        work_item_id=checkpoint.work_item_id,
        history_json=_serialize_history(messages),
        round_count=_count_history_rounds(messages),
    )
    return messages


def _build_output(
    result_output: AgentOutput,
    all_msgs: list[ModelMessage],
    scope: ApprovalScope,
    rt: Runtime,
) -> WorkItemOutput:
    """Convert agent output to a WorkItemOutput, handling deferred approvals."""
    if isinstance(result_output, DeferredToolRequests):
        return WorkItemOutput(
            deferred_tool_requests_json=serialize_deferred_requests(
                result_output,
                scope=scope,
                approval_store=rt.approval_store,
                key_manager=rt.key_manager,
                tool_policy=rt.tool_policy,
            ),
            message_history_json=_serialize_history(all_msgs),
        )
    return WorkItemOutput(
        text=result_output,
        message_history_json=_serialize_history(all_msgs),
    )


def _run_streaming(
    rt: Runtime,
    turn: _TurnInput,
    stream_handle: StreamHandle,
) -> WorkItemOutput:
    """Execute an agent turn with real-time streaming output."""
    output_type: list[type[AgentOutput]] = [str, DeferredToolRequests]

    async def _stream() -> WorkItemOutput:
        try:
            async with rt.agent.run_stream(
                turn.prompt,
                deps=turn.deps,
                message_history=turn.history,
                output_type=output_type,
                deferred_tool_results=turn.deferred_results,
            ) as stream:
                async for chunk in stream.stream_text(delta=True):
                    stream_handle.write(chunk)
                result_output: AgentOutput = await stream.get_output()
                all_msgs = stream.all_messages()
        finally:
            stream_handle.close()

        return _build_output(result_output, all_msgs, turn.scope, rt)

    return asyncio.run(_stream())


def _run_sync(
    rt: Runtime,
    turn: _TurnInput,
) -> WorkItemOutput:
    """Execute an agent turn synchronously without streaming."""
    output_type: list[type[AgentOutput]] = [str, DeferredToolRequests]
    result = rt.agent.run_sync(
        turn.prompt,
        deps=turn.deps,
        message_history=turn.history,
        output_type=output_type,
        deferred_tool_results=turn.deferred_results,
    )
    return _build_output(result.output, result.all_messages(), turn.scope, rt)


@DBOS.step()
def run_agent_step(work_item_dict: dict[str, Any]) -> dict[str, Any]:
    """Execute one work item and return a serialized WorkItemOutput."""
    rt = get_runtime()
    item = WorkItem.model_validate(work_item_dict)
    recovered_history_json = load_checkpoint(rt.history_db_path, item.id)
    history_json = recovered_history_json or item.input.message_history_json
    history = _deserialize_history(history_json)
    deps = AgentDeps(backend=rt.backend)
    agent_name = rt.agent.name or os.getenv("DBOS_AGENT_NAME", "chat")
    approval_context_id = item.input.approval_context_id or item.id
    scope = build_approval_scope(approval_context_id, rt.backend, agent_name)

    deferred_results: DeferredToolResults | None = None
    if item.input.deferred_tool_results_json:
        deferred_results = deserialize_deferred_results(
            item.input.deferred_tool_results_json,
            scope=scope,
            approval_store=rt.approval_store,
            key_manager=rt.key_manager,
        )

    turn = _TurnInput(
        prompt=item.input.prompt,
        deps=deps,
        history=history,
        deferred_results=deferred_results,
        scope=scope,
    )
    stream_handle = take_stream(item.id)
    checkpoint_token: Token[_CheckpointContext | None] = _active_checkpoint_context.set(
        _CheckpointContext(db_path=rt.history_db_path, work_item_id=item.id)
    )

    try:
        if stream_handle is not None:
            output = _run_streaming(rt, turn, stream_handle)
        else:
            output = _run_sync(rt, turn)
    finally:
        _active_checkpoint_context.reset(checkpoint_token)

    clear_checkpoint(rt.history_db_path, item.id)
    return output.model_dump()


@DBOS.workflow()
def execute_work_item(work_item_dict: dict[str, Any]) -> dict[str, Any]:
    """Execute any work item from the DBOS queue."""
    return run_agent_step(work_item_dict)


def enqueue(item: WorkItem) -> str:
    """Enqueue a work item and return its id."""
    with SetEnqueueOptions(priority=int(item.priority)):
        work_queue.enqueue(execute_work_item, item.model_dump())
    return item.id


def enqueue_and_wait(item: WorkItem) -> WorkItemOutput:
    """Enqueue a work item and block until complete."""
    with SetEnqueueOptions(priority=int(item.priority)):
        handle = work_queue.enqueue(execute_work_item, item.model_dump())
    raw = handle.get_result()
    return WorkItemOutput.model_validate(raw)
