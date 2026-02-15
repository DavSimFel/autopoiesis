"""Work item types for DBOS-backed priority queue execution.

A WorkItem is the universal unit of work. It has structured inputs, outputs,
and an arbitrary payload. Everything — chat, research, code, review — is a
WorkItem flowing through the same queue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


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

    `message_history_json` carries serialized PydanticAI message history
    for multi-turn conversation continuity. It is optional — single-turn
    background tasks leave it None.
    """

    prompt: str
    message_history_json: str | None = None


class WorkItemOutput(BaseModel):
    """Structured outputs from agent execution.

    `text` is the agent's response. `message_history_json` is the updated
    conversation history (serialized) for the next turn.
    """

    text: str
    message_history_json: str | None = None


class WorkItem(BaseModel):
    """Single unit of work flowing through the DBOS priority queue.

    - `input`: what the agent receives (prompt + optional history)
    - `output`: what the agent produced (filled after execution, None before)
    - `payload`: arbitrary caller metadata (labels, source info, etc.)
    """

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    type: WorkItemType
    priority: WorkItemPriority = WorkItemPriority.NORMAL
    input: WorkItemInput
    output: WorkItemOutput | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    max_tokens: int | None = None
