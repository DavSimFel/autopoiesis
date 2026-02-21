"""Inspect AI solver that runs Autopoiesis batch mode via subprocess."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inspect_ai.model import ModelOutput
from inspect_ai.solver import Generate, TaskState, solver

DEFAULT_TIMEOUT_SECONDS = 60
STORE_KEY_RESPONSE = "autopoiesis_response"
STORE_KEY_METRICS = "autopoiesis_metrics"


@dataclass(frozen=True)
class BatchMetrics:
    """Parsed metrics from one Autopoiesis batch run."""

    success: bool
    response_text: str
    error: str | None
    elapsed_seconds: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    tool_call_count: int
    cost: float | None
    approval_rounds: int
    raw_payload: dict[str, Any]


def _as_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    parsed: float | None = None
    if isinstance(value, float):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = float(stripped)
        except ValueError:
            return None
    if parsed is None:
        return None
    return int(parsed)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _first_numeric(payload: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _as_float(payload.get(key))
        if value is not None:
            return value
    return None


def _extract_usage(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    usage = _as_mapping(payload.get("usage"))
    if usage:
        return usage
    token_usage = _as_mapping(payload.get("token_usage"))
    if token_usage:
        return token_usage
    metrics = _as_mapping(payload.get("metrics"))
    return _as_mapping(metrics.get("usage"))


def _extract_token_counts(payload: Mapping[str, Any]) -> tuple[int | None, int | None, int | None]:
    usage = _extract_usage(payload)
    prompt_tokens = _as_int(usage.get("prompt_tokens"))
    if prompt_tokens is None:
        prompt_tokens = _as_int(usage.get("input_tokens"))

    completion_tokens = _as_int(usage.get("completion_tokens"))
    if completion_tokens is None:
        completion_tokens = _as_int(usage.get("output_tokens"))

    total_tokens = _as_int(usage.get("total_tokens"))
    if total_tokens is None:
        total_tokens = _as_int(payload.get("total_tokens"))
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    return prompt_tokens, completion_tokens, total_tokens


def _extract_tool_call_count(payload: Mapping[str, Any]) -> int:
    metrics = _as_mapping(payload.get("metrics"))
    candidates = (
        payload.get("tool_call_count"),
        payload.get("tool_calls"),
        metrics.get("tool_call_count"),
        metrics.get("tool_calls"),
    )
    for candidate in candidates:
        parsed = _as_int(candidate)
        if parsed is not None:
            return max(parsed, 0)
        if isinstance(candidate, list):
            return len(candidate)
    tool_calls_list = payload.get("tool_calls")
    if isinstance(tool_calls_list, list):
        return len(tool_calls_list)
    return 0


def _extract_cost(payload: Mapping[str, Any]) -> float | None:
    metrics = _as_mapping(payload.get("metrics"))
    usage = _extract_usage(payload)
    return _first_numeric(
        {
            "cost": payload.get("cost"),
            "estimated_cost": payload.get("estimated_cost"),
            "usage_cost": usage.get("cost"),
            "metrics_cost": metrics.get("cost"),
        },
        ("cost", "estimated_cost", "usage_cost", "metrics_cost"),
    )


def _read_batch_output(output_path: Path) -> dict[str, Any]:
    if not output_path.exists():
        return {}
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _process_error_message(result: subprocess.CompletedProcess[str]) -> str:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    details = stderr if stderr else stdout
    if details:
        return f"autopoiesis exited with code {result.returncode}: {details}"
    return f"autopoiesis exited with code {result.returncode}."


def _build_metrics(
    payload: Mapping[str, Any],
    *,
    fallback_elapsed: float,
    process_error: str | None,
) -> BatchMetrics:
    prompt_tokens, completion_tokens, total_tokens = _extract_token_counts(payload)
    elapsed_seconds = _first_numeric(payload, ("elapsed_seconds", "elapsed"))
    if elapsed_seconds is None:
        elapsed_seconds = fallback_elapsed

    success = bool(payload.get("success", process_error is None))
    result_text = payload.get("result")
    response_text = str(result_text) if isinstance(result_text, str) else ""

    error_text = payload.get("error")
    parsed_error = str(error_text) if isinstance(error_text, str) else None
    final_error = parsed_error or process_error

    if not response_text and final_error:
        response_text = f"Error: {final_error}"

    return BatchMetrics(
        success=success,
        response_text=response_text,
        error=final_error,
        elapsed_seconds=elapsed_seconds,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        tool_call_count=_extract_tool_call_count(payload),
        cost=_extract_cost(payload),
        approval_rounds=_as_int(payload.get("approval_rounds")) or 0,
        raw_payload=dict(payload),
    )


def _run_batch(prompt: str, timeout_seconds: int) -> BatchMetrics:
    with tempfile.NamedTemporaryFile(
        prefix="autopoiesis-eval-",
        suffix=".json",
        delete=False,
    ) as tmp:
        output_path = Path(tmp.name)

    command = [
        "autopoiesis",
        "--no-approval",
        "run",
        "--task",
        prompt,
        "--output",
        str(output_path),
        "--timeout",
        str(timeout_seconds),
    ]

    process_error: str | None = None
    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 5,
        )
        if completed.returncode != 0:
            process_error = _process_error_message(completed)
    except FileNotFoundError:
        process_error = "autopoiesis command was not found in PATH."
    except subprocess.TimeoutExpired:
        process_error = f"autopoiesis subprocess timed out after {timeout_seconds}s."

    payload = _read_batch_output(output_path)
    elapsed = time.monotonic() - start
    output_path.unlink(missing_ok=True)
    return _build_metrics(payload, fallback_elapsed=elapsed, process_error=process_error)


def _store_metrics(state: TaskState, metrics: BatchMetrics) -> None:
    state.store.set(STORE_KEY_RESPONSE, metrics.response_text)
    state.store.set(
        STORE_KEY_METRICS,
        {
            "success": metrics.success,
            "error": metrics.error,
            "elapsed_seconds": metrics.elapsed_seconds,
            "prompt_tokens": metrics.prompt_tokens,
            "completion_tokens": metrics.completion_tokens,
            "total_tokens": metrics.total_tokens,
            "tool_call_count": metrics.tool_call_count,
            "cost": metrics.cost,
            "approval_rounds": metrics.approval_rounds,
            "raw_payload": metrics.raw_payload,
        },
    )


@solver
def autopoiesis_solver(timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> object:
    """Run each Inspect sample through `autopoiesis --no-approval run ...`."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        del generate
        prompt = state.input if isinstance(state.input, str) else str(state.input)
        metrics = _run_batch(prompt, timeout_seconds)
        _store_metrics(state, metrics)
        state.output = ModelOutput.from_content(
            model="autopoiesis-batch",
            content=metrics.response_text,
        )
        return state

    return solve
