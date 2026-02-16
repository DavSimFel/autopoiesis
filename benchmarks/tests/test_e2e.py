"""End-to-end test harness for autopoiesis via batch mode.

Invokes ``python chat.py run`` for each test task and validates
the structured JSON output. Designed to run locally without Docker
or Harbor — exercises the same code path the Harbor adapter uses.

Requires:
    - autopoiesis installed and runnable (``python chat.py run --help``)
    - An AI provider key (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)

Run:
    cd benchmarks && python -m pytest tests/test_e2e.py -v
    # or: cd benchmarks && ./run.sh
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .e2e_tasks import TASKS, E2ETask

# Resolve the autopoiesis repo root (two levels up from this file).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHAT_PY = _REPO_ROOT / "chat.py"

# Skip all e2e tests if no provider key is set.
_HAS_PROVIDER = any(
    os.environ.get(k)
    for k in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    )
)

pytestmark = pytest.mark.skipif(
    not _HAS_PROVIDER,
    reason="No AI provider key set (need ANTHROPIC_API_KEY etc.)",
)


def _run_task(task: E2ETask, tmp_path: Path) -> dict[str, object]:
    """Execute a single task via batch mode CLI."""
    output_file = tmp_path / f"{task.name}.json"

    cmd = [
        sys.executable,
        str(_CHAT_PY),
        "run",
        "--task",
        task.instruction,
        "--output",
        str(output_file),
        "--timeout",
        str(task.timeout_sec),
        "--no-approval",
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=task.timeout_sec + 30,
        cwd=str(_REPO_ROOT),
    )

    if output_file.exists():
        text = output_file.read_text(encoding="utf-8")
        result: dict[str, object] = json.loads(text)
        return result

    # Fall back to stdout if file wasn't written.
    stdout = proc.stdout.strip()
    if stdout:
        result = json.loads(stdout)
        return result

    return {
        "success": False,
        "result": None,
        "error": (
            f"No output produced. "
            f"exit={proc.returncode} "
            f"stderr={proc.stderr[:500]}"
        ),
        "approval_rounds": 0,
        "elapsed_seconds": 0.0,
    }


# Generate one pytest test per task.
@pytest.mark.parametrize(
    "task",
    TASKS,
    ids=[t.name for t in TASKS],
)
def test_e2e_task(task: E2ETask, tmp_path: Path) -> None:
    """Run a single e2e task and validate the result."""
    result = _run_task(task, tmp_path)
    error = task.validate(result)
    if error is not None:
        pytest.fail(
            f"[{task.category}/{task.name}] {error}\n"
            f"Result: {json.dumps(result, indent=2)}"
        )
