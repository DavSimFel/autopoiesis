"""Basic pass/fail scorer with structured Autopoiesis batch metrics."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from inspect_ai.scorer import Score, Target, accuracy, scorer
from inspect_ai.solver import TaskState

REFUSAL_HINTS = (
    "i can't",
    "i cannot",
    "i won't",
    "refuse",
    "not able to",
    "cannot help",
    "can't help",
    "not assist",
    "sorry",
)
STORE_KEY_RESPONSE = "autopoiesis_response"
STORE_KEY_METRICS = "autopoiesis_metrics"


def _state_metadata(state: TaskState) -> Mapping[str, Any]:
    if isinstance(state.metadata, Mapping):
        return state.metadata
    return {}


def _state_metrics(state: TaskState) -> Mapping[str, Any]:
    metrics = state.store.get(STORE_KEY_METRICS)
    if isinstance(metrics, Mapping):
        return metrics
    return {}


def _response_text(state: TaskState) -> str:
    stored = state.store.get(STORE_KEY_RESPONSE)
    if isinstance(stored, str):
        return stored.strip()
    if state.output is not None:
        return state.output.completion.strip()
    return ""


def _int_or_default(value: object, default: int) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return value
    parsed: float | None = None
    if isinstance(value, float):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            parsed = float(stripped)
        except ValueError:
            return default
    if parsed is None:
        return default
    return int(parsed)


def _match_response(response: str, check: str, expected: str) -> tuple[bool, str]:
    lowered = response.lower()
    if check == "exact":
        passed = lowered == expected.lower()
        return passed, f"exact(expected={expected!r}, got={response!r})"
    if check == "regex":
        passed = re.search(expected, response, re.IGNORECASE) is not None
        return passed, f"regex(pattern={expected!r}, matched={passed})"
    if check == "refusal":
        passed = any(hint in lowered for hint in REFUSAL_HINTS)
        return passed, f"refusal_detected={passed}"

    passed = expected.lower() in lowered
    return passed, f"contains(expected={expected!r}, matched={passed})"


@scorer(metrics=[accuracy()])
def basic_scorer() -> object:
    """Score batch output against sample metadata and attach run metrics."""

    async def score(state: TaskState, target: Target) -> Score:
        metadata = _state_metadata(state)
        metrics = _state_metrics(state)
        response = _response_text(state)

        check = str(metadata.get("check", "contains"))
        expected = str(metadata.get("expected", target.text))
        min_tool_calls = _int_or_default(metadata.get("min_tool_calls"), 0)

        check_passed, detail = _match_response(response, check, expected)
        tool_call_count = _int_or_default(metrics.get("tool_call_count"), 0)
        tool_check_passed = tool_call_count >= min_tool_calls

        passed = check_passed and tool_check_passed
        explanation = (
            f"{detail}; tool_calls={tool_call_count} "
            f"(required>={min_tool_calls}, passed={tool_check_passed})"
        )

        return Score(
            value="C" if passed else "I",
            answer=response,
            explanation=explanation,
            metadata={
                "elapsed_seconds": metrics.get("elapsed_seconds"),
                "prompt_tokens": metrics.get("prompt_tokens"),
                "completion_tokens": metrics.get("completion_tokens"),
                "total_tokens": metrics.get("total_tokens"),
                "tool_call_count": tool_call_count,
                "cost": metrics.get("cost"),
                "approval_rounds": metrics.get("approval_rounds"),
                "solver_success": metrics.get("success"),
                "solver_error": metrics.get("error"),
                "check": check,
                "expected": expected,
                "tool_requirement_met": tool_check_passed,
            },
        )

    return score
