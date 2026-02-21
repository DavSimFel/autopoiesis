"""Shared loop-guard limits and warning threshold helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

_WARNING_RATIO = 0.8


@dataclass(frozen=True)
class LoopGuards:
    """Runtime loop and budget limits for a single agent."""

    queue_poll_max_iterations: int = 900
    deferred_max_iterations: int = 10
    deferred_timeout_seconds: float = 300.0
    tool_loop_max_iterations: int = 40
    work_item_token_budget: int = 120_000
    work_item_timeout_seconds: float = 300.0


def warning_threshold(limit: int) -> int:
    """Return the 80% warning threshold for an integer limit."""
    return max(1, math.ceil(limit * _WARNING_RATIO))


def warning_timeout(limit_seconds: float) -> float:
    """Return the 80% warning threshold for a timeout in seconds."""
    return limit_seconds * _WARNING_RATIO


def resolve_loop_guards(runtime: object) -> LoopGuards:
    """Return runtime loop guards or fallback defaults for test doubles."""
    raw = getattr(runtime, "loop_guards", None)
    return raw if isinstance(raw, LoopGuards) else LoopGuards()
