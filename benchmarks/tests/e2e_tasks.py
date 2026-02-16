"""End-to-end test task definitions for autopoiesis capabilities.

Each task is a structured test case that exercises a specific autopoiesis
feature through the batch-mode CLI. Tasks include an instruction, a
timeout, and a validator that checks the batch result JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class E2ETask:
    """A single end-to-end test case."""

    name: str
    category: str
    instruction: str
    timeout_sec: int
    validate: Callable[[dict[str, object]], str | None]


def _check_success(result: dict[str, object]) -> str | None:
    """Validate that the batch run succeeded."""
    if not result.get("success"):
        error = result.get("error", "unknown error")
        return f"Task failed: {error}"
    return None


def _check_has_result(result: dict[str, object]) -> str | None:
    """Validate success and non-empty result text."""
    err = _check_success(result)
    if err:
        return err
    text = result.get("result")
    if not text or not str(text).strip():
        return "Result text is empty"
    return None


def _check_timeout(result: dict[str, object]) -> str | None:
    """Validate that the task timed out as expected."""
    if result.get("success"):
        return "Expected timeout but task succeeded"
    error = str(result.get("error", ""))
    if "timeout" not in error.lower():
        return f"Expected timeout error, got: {error}"
    return None


TASKS: list[E2ETask] = [
    # --- Basic chat ---
    E2ETask(
        name="basic_greeting",
        category="chat",
        instruction=(
            "Reply with exactly: HELLO_AUTOPOIESIS. Do not add any other text."
        ),
        timeout_sec=30,
        validate=_check_has_result,
    ),
    E2ETask(
        name="reasoning",
        category="chat",
        instruction=("What is 17 * 23? Reply with only the number."),
        timeout_sec=30,
        validate=_check_has_result,
    ),
    # --- File operations ---
    E2ETask(
        name="file_create",
        category="file_ops",
        instruction=(
            "Create a file called /tmp/autopoiesis_test.txt "
            "containing the text 'benchmark_marker_42'. "
            "Then confirm you created it."
        ),
        timeout_sec=60,
        validate=_check_has_result,
    ),
    E2ETask(
        name="file_read",
        category="file_ops",
        instruction=("Read the file /etc/hostname and tell me its contents."),
        timeout_sec=60,
        validate=_check_has_result,
    ),
    # --- Memory store/recall ---
    E2ETask(
        name="memory_store",
        category="memory",
        instruction=(
            "Store the following in your memory: "
            "'The secret code is ALPHA-7742'. "
            "Confirm that you stored it."
        ),
        timeout_sec=60,
        validate=_check_has_result,
    ),
    # --- Knowledge search ---
    E2ETask(
        name="knowledge_search",
        category="knowledge",
        instruction=(
            "Search your knowledge base for any entries. "
            "Report what you find, or say 'no entries found' "
            "if empty."
        ),
        timeout_sec=60,
        validate=_check_has_result,
    ),
    # --- Topic activation ---
    E2ETask(
        name="topic_activation",
        category="topics",
        instruction=(
            "List all available topics. If none exist, say "
            "'no topics available'."
        ),
        timeout_sec=60,
        validate=_check_has_result,
    ),
    # --- Timeout handling ---
    E2ETask(
        name="forced_timeout",
        category="timeout",
        instruction=(
            "Count from 1 to 1000000, saying each number "
            "out loud one at a time. Do not skip any."
        ),
        timeout_sec=5,
        validate=_check_timeout,
    ),
]
