"""Non-interactive batch execution for programmatic agent invocation.

Dependencies: agent.runtime, models, run_simple
Wired in: chat.py → main() (via ``run`` subcommand)
"""

from __future__ import annotations

import json
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from autopoiesis.agent.runtime import get_runtime
from autopoiesis.models import AgentDeps
from autopoiesis.run_simple import run_simple


@dataclass(frozen=True)
class BatchResult:
    """Structured output from a batch run."""

    success: bool
    result: str | None
    error: str | None
    approval_rounds: int
    elapsed_seconds: float


def format_output(result: BatchResult) -> str:
    """Serialize a BatchResult to JSON."""
    return json.dumps(
        {
            "success": result.success,
            "result": result.result,
            "error": result.error,
            "approval_rounds": result.approval_rounds,
            "elapsed_seconds": round(result.elapsed_seconds, 3),
        },
        ensure_ascii=True,
        allow_nan=False,
        indent=2,
    )


def _read_task_stdin() -> str:
    """Read task from stdin, stripping trailing whitespace."""
    task = sys.stdin.read().strip()
    if not task:
        raise SystemExit("Error: empty task from stdin.")
    return task


def _install_timeout(timeout: int) -> None:
    """Set a SIGALRM-based timeout (Unix only)."""

    def _on_timeout(_signum: int, _frame: object) -> None:
        raise TimeoutError(f"Batch run exceeded {timeout}s timeout.")

    signal.signal(signal.SIGALRM, _on_timeout)
    signal.alarm(timeout)


def run_batch(
    task: str | None,
    *,
    output_path: str | None = None,
    timeout: int | None = None,
) -> None:
    """Execute a single task non-interactively and exit."""
    resolved_task = _read_task_stdin() if task is None or task == "-" else task

    if timeout is not None and timeout > 0:
        _install_timeout(timeout)

    rt = get_runtime()
    deps = AgentDeps(backend=rt.backend)
    start = time.monotonic()

    try:
        simple_result = run_simple(rt.agent, resolved_task, deps)
        batch_result = BatchResult(
            success=True,
            result=simple_result.text,
            error=None,
            approval_rounds=simple_result.approval_rounds,
            elapsed_seconds=time.monotonic() - start,
        )
    except TimeoutError as exc:
        batch_result = BatchResult(
            success=False,
            result=None,
            error=str(exc),
            approval_rounds=0,
            elapsed_seconds=time.monotonic() - start,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        batch_result = BatchResult(
            success=False,
            result=None,
            error=str(exc),
            approval_rounds=0,
            elapsed_seconds=time.monotonic() - start,
        )

    output_json = format_output(batch_result)

    if output_path:
        Path(output_path).write_text(output_json + "\n", encoding="utf-8")
    else:
        print(output_json)

    sys.exit(0 if batch_result.success else 1)
