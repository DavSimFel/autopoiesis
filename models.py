"""Work item types for DBOS-backed priority queue execution.

A WorkItem is the universal unit of work. It has structured inputs, outputs,
and an arbitrary payload. Everything — chat, research, code, review — is a
WorkItem flowing through the same queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from pydantic_ai_backends import LocalBackend


@dataclass
class AgentDeps:
    """Runtime dependencies injected into agent turns.

    ``backend`` is an explicit field so ``AgentDeps`` structurally matches the
    console toolset dependency protocol used by ``pydantic-ai-backend``.
    """

    backend: LocalBackend


class WorkItemPriority(IntEnum):
    """Priority levels for queued work. Lower numbers dequeue first."""

    CRITICAL = 1
    HIGH = 10
    NORMAL = 100
    LOW = 1000
    IDLE = 10000


class WorkItemType(StrEnum):
    """Categorization for work item intent."""

    CHAT = "chat"
    RESEARCH = "research"
    CODE = "code"
    REVIEW = "review"
    MERGE = "merge"
    CUSTOM = "custom"


class WorkItemInput(BaseModel):
    """Structured inputs for agent execution.

    ``prompt`` is the user's message — required for initial turns, None when
    resuming after deferred tool approval (context is in message history).
    ``message_history_json`` carries serialized PydanticAI message history
    for multi-turn conversation continuity. ``deferred_tool_results_json``
    carries serialized approval decisions from a previous deferred tool
    request, allowing the agent to resume after human-in-the-loop approval.
    """

    prompt: str | None = None
    message_history_json: str | None = None
    deferred_tool_results_json: str | None = None


class WorkItemOutput(BaseModel):
    """Structured outputs from agent execution.

    When the agent completes normally, ``text`` holds the response and
    ``deferred_tool_requests_json`` is None. When the agent encounters
    tools requiring approval, ``text`` is None and
    ``deferred_tool_requests_json`` holds the serialized approval requests
    for the caller to resolve.
    """

    text: str | None = None
    message_history_json: str | None = None
    deferred_tool_requests_json: str | None = None


class WorkItem(BaseModel):
    """Single unit of work flowing through the DBOS priority queue.

    - ``input``: what the agent receives (prompt + optional history + optional approvals)
    - ``output``: what the agent produced (filled after execution, None before)
    - ``payload``: arbitrary caller metadata (labels, source, etc.). Reserved for
      future use — not consumed by the worker yet.
    """

    id: str = Field(default_factory=lambda: uuid4().hex)
    type: WorkItemType
    priority: WorkItemPriority = WorkItemPriority.NORMAL
    input: WorkItemInput
    output: WorkItemOutput | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
