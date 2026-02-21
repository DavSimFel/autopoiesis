"""Checkpoint serialization and scope helpers for worker execution.

Dependencies: store.history
Wired in: agent.worker
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse

from autopoiesis.store.history import save_checkpoint


@dataclass(frozen=True)
class _CheckpointContext:
    """Per-run checkpoint metadata used by history processors."""

    db_path: str
    work_item_id: str


_active_checkpoint_context: ContextVar[_CheckpointContext | None] = ContextVar(
    "active_checkpoint_context",
    default=None,
)


def deserialize_history(history_json: str | None) -> list[ModelMessage]:
    """Deserialize model message history from JSON."""
    if not history_json:
        return []
    return ModelMessagesTypeAdapter.validate_json(history_json)


def serialize_history(messages: list[ModelMessage]) -> str:
    """Serialize model message history to JSON."""
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
        history_json=serialize_history(messages),
        round_count=_count_history_rounds(messages),
    )
    return messages


@contextmanager
def checkpoint_scope(db_path: str, work_item_id: str) -> Iterator[None]:
    """Activate checkpoint persistence for the current worker execution."""
    token = _active_checkpoint_context.set(
        _CheckpointContext(db_path=db_path, work_item_id=work_item_id)
    )
    try:
        yield
    finally:
        _active_checkpoint_context.reset(token)
