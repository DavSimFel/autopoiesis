"""Task payload types for DBOS-backed background queue execution."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskPriority(IntEnum):
    """Priority levels for queued work where lower numbers run first."""

    CRITICAL = 1
    HIGH = 10
    NORMAL = 100
    LOW = 1000
    IDLE = 10000


class TaskType(StrEnum):
    """Categorization for background task intent."""

    CHAT = "chat"
    RESEARCH = "research"
    CODE = "code"
    REVIEW = "review"
    MERGE = "merge"
    CUSTOM = "custom"


class TaskPayload(BaseModel):
    """Single queued unit of background agent work."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    type: TaskType
    priority: TaskPriority = TaskPriority.NORMAL
    prompt: str
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    max_tokens: int | None = None
