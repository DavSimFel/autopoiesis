"""DBOS worker and queue helpers for chat work items.

Dependencies: agent.runtime, approval.chat_approval, approval.types,
    display.stream_formatting, display.streaming, infra.otel_tracing,
    infra.work_queue, models, store.history
Wired in: agent/cli.py → _run_turn()
"""

from __future__ import annotations

import logging
import os
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai import DeferredToolRequests
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
)
from pydantic_ai.tools import DeferredToolResults

from autopoiesis.agent.loop_guards import resolve_loop_guards, warning_threshold
from autopoiesis.agent.runtime import Runtime, get_runtime
from autopoiesis.agent.topic_activation import activate_topic_ref
from autopoiesis.agent.turn_execution import (
    TurnExecutionParams,
    WorkItemLimitExceededError,
    run_turn,
)
from autopoiesis.display.streaming import take_stream
from autopoiesis.infra import otel_tracing
from autopoiesis.infra.approval.chat_approval import (
    build_approval_scope,
    deserialize_deferred_results,
    serialize_deferred_requests,
)
from autopoiesis.infra.approval.types import ApprovalScope
from autopoiesis.infra.work_queue import dispatch_workitem
from autopoiesis.models import AgentDeps, WorkItem, WorkItemOutput
from autopoiesis.store.conversation_log import append_turn, rotate_logs
from autopoiesis.store.history import clear_checkpoint, load_checkpoint, save_checkpoint
from autopoiesis.store.result_store import rotate_results

try:
    from dbos import DBOS, SetEnqueueOptions
except ModuleNotFoundError as exc:
    missing_package = exc.name or "unknown package"
    raise SystemExit(
        f"Missing DBOS dependency package `{missing_package}`. Run `uv sync` so "
        "`pydantic-ai-slim[dbos,mcp]` and `dbos` are installed."
    ) from exc


class DeferredApprovalLockedError(RuntimeError):
    """Raised when deferred approvals are attempted with locked approval keys."""


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
        if not rt.approval_unlocked:
            raise DeferredApprovalLockedError("Deferred approvals require unlocked approval keys.")
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


_log = logging.getLogger(__name__)
_QUEUE_POLL_INTERVAL_SECONDS = 1.0

# Workflow statuses treated as terminal (no more polling needed).
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"SUCCESS", "ERROR", "MAX_RECOVERY_ATTEMPTS_EXCEEDED", "CANCELLED"}
)


def _wrap_agent_run_error(error: AgentRunError) -> RuntimeError:
    """Convert non-picklable pydantic-ai errors into a built-in RuntimeError."""
    return RuntimeError(f"{error.__class__.__name__}: {error}")


@DBOS.step()
def run_agent_step(work_item_dict: dict[str, Any]) -> dict[str, Any]:
    """Execute one work item and return a serialized WorkItemOutput.

    Uses :func:`run_turn` for bounded execution with loop guards.  If a guard
    limit is reached, a partial-result ``WorkItemOutput`` is returned rather
    than raising so the DBOS workflow completes cleanly.
    """
    rt = get_runtime()
    item = WorkItem.model_validate(work_item_dict)

    # Auto-activate topic when topic_ref is set (before agent executes)
    if item.topic_ref:
        activate_topic_ref(item.topic_ref)

    recovered_history_json = load_checkpoint(rt.history_db_path, item.id)
    history_json = recovered_history_json or item.input.message_history_json
    history = _deserialize_history(history_json)
    deps = AgentDeps(backend=rt.backend, approval_unlocked=rt.approval_unlocked)
    agent_name = rt.agent_name
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

    stream_handle = take_stream(item.id)
    checkpoint_token: Token[_CheckpointContext | None] = _active_checkpoint_context.set(
        _CheckpointContext(db_path=rt.history_db_path, work_item_id=item.id)
    )

    provider_name = os.getenv("AI_PROVIDER", "unknown")
    model_name = os.getenv("ANTHROPIC_MODEL") or os.getenv("OPENROUTER_MODEL") or "unknown"
    span_attrs: dict[str, str | int | float | bool] = {
        "autopoiesis.model_name": model_name,
        "autopoiesis.provider": provider_name,
        "autopoiesis.workflow_id": item.id,
    }

    with otel_tracing.trace_span("agent.run", attributes=span_attrs) as result_attrs:
        try:
            try:
                turn_exec = run_turn(
                    rt,
                    TurnExecutionParams(
                        work_item_id=item.id,
                        prompt=item.input.prompt,
                        deps=deps,
                        history=history,
                        deferred_results=deferred_results,
                        stream_handle=stream_handle,
                    ),
                )
                output = _build_output(turn_exec.output, turn_exec.messages, scope, rt)
            except WorkItemLimitExceededError as exc:
                # Graceful degradation: return partial result instead of crashing.
                _log.warning(
                    "Work item %s stopped by loop guard: %s",
                    item.id,
                    exc.user_message,
                )
                output = WorkItemOutput(
                    text=exc.user_message,
                    message_history_json=_serialize_history(history),
                )
            except AgentRunError as exc:
                raise _wrap_agent_run_error(exc) from exc
        finally:
            _active_checkpoint_context.reset(checkpoint_token)

        result_attrs["autopoiesis.completed"] = True

    clear_checkpoint(rt.history_db_path, item.id)

    # --- Conversation logging (T2 reflection) ---
    if rt.log_conversations and rt.knowledge_root is not None and output.message_history_json:
        try:
            messages = _deserialize_history(output.message_history_json)
            append_turn(rt.knowledge_root, rt.knowledge_db_path, rt.agent_name, messages)
            rotate_logs(rt.knowledge_root, rt.agent_name, rt.conversation_log_retention_days)
        except Exception:
            _log.warning("Conversation logging failed for agent %s", rt.agent_name, exc_info=True)

    # --- Persistent result rotation ---
    rotate_results(Path(rt.backend.root_dir) / "tmp", rt.tmp_retention_days, rt.tmp_max_size_mb)

    return output.model_dump()


@DBOS.workflow()
def execute_work_item(work_item_dict: dict[str, Any]) -> dict[str, Any]:
    """Execute any work item from the DBOS queue."""
    return run_agent_step(work_item_dict)


def poll_workflow_result(handle: Any, guards: Any, work_item_id: str) -> Any:
    """Poll a DBOS workflow handle bounded by ``guards.queue_poll_max_iterations``.

    Sleeps ``_QUEUE_POLL_INTERVAL_SECONDS`` between polls and logs a warning
    when 80 % of the iteration budget has been consumed.  Raises
    ``RuntimeError`` if the budget is exhausted or the workflow ends with a
    non-SUCCESS terminal status.
    """
    max_iter = guards.queue_poll_max_iterations
    threshold = warning_threshold(max_iter)
    warned = False

    for poll_iter in range(max_iter):
        if not warned and poll_iter >= threshold:
            _log.warning(
                "Queue poll for work item %s reached 80%% of max iterations (%d/%d).",
                work_item_id,
                poll_iter,
                max_iter,
            )
            warned = True

        status = handle.get_status()
        if status.status in _TERMINAL_STATUSES:
            if status.status == "SUCCESS":
                return handle.get_result()
            raise RuntimeError(
                f"Work item {work_item_id} workflow ended with unexpected status: {status.status}."
            )
        time.sleep(_QUEUE_POLL_INTERVAL_SECONDS)

    raise RuntimeError(
        f"Queue poll for work item {work_item_id} exceeded {max_iter} iterations "
        f"({max_iter * _QUEUE_POLL_INTERVAL_SECONDS:.0f}s max)."
    )


def enqueue(item: WorkItem) -> str:
    """Enqueue a work item and return its id via :func:`dispatch_workitem`."""
    queue = dispatch_workitem(item)
    with SetEnqueueOptions(priority=int(item.priority)):
        queue.enqueue(execute_work_item, item.model_dump())
    return item.id


def enqueue_and_wait(item: WorkItem) -> WorkItemOutput:
    """Enqueue a work item and block until complete.

    Poll the DBOS workflow handle up to ``guards.queue_poll_max_iterations``
    times (one second apart) before raising ``RuntimeError``.  Routes to the
    correct per-agent queue via :func:`dispatch_workitem`.
    """
    rt = get_runtime()
    guards = resolve_loop_guards(rt)
    queue = dispatch_workitem(item)
    with SetEnqueueOptions(priority=int(item.priority)):
        handle = queue.enqueue(execute_work_item, item.model_dump())
    raw = poll_workflow_result(handle, guards, item.id)
    return WorkItemOutput.model_validate(raw)
