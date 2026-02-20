"""Persistent storage for tool results and shell outputs.

Tool call results and shell outputs are persisted under the agent's ``tmp/``
directory in date-based subdirectories for easy retention cleanup.

Storage layout::

    {tmp_dir}/
    ├── tool-results/
    │   └── YYYY-MM-DD/
    │       └── {tool_name}_{short_hash}.out
    └── shell/
        └── YYYY-MM-DD/
            └── {cmd_short_hash}.log

Dependencies: (none — leaf module)
Wired in: agent/truncation.py, tools/exec_tool.py, agent/worker.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _today_str() -> str:
    """Return today's date as ``YYYY-MM-DD`` (UTC)."""
    return datetime.now(UTC).date().isoformat()


def _short_hash(text: str, length: int = 8) -> str:
    """Return a short hex digest of *text*."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:length]


def _ensure_date_dir(base: Path) -> Path:
    """Create and return today's date subdirectory under *base*."""
    date_dir = base / _today_str()
    date_dir.mkdir(parents=True, exist_ok=True)
    return date_dir


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def store_tool_result(
    tmp_dir: Path,
    tool_name: str,
    content: str,
    metadata: dict[str, object],
) -> Path:
    """Persist full tool output to ``{tmp_dir}/tool-results/YYYY-MM-DD/``.

    The file name is ``{tool_name}_{short_hash(content)}.out``.  A small
    JSON header containing *metadata* is prepended so the file is
    self-describing.

    Args:
        tmp_dir: Agent ``tmp/`` directory (``AgentPaths.tmp``).
        tool_name: Name of the tool that produced the output.
        content: Full tool result text.
        metadata: Arbitrary key-value pairs to include in the header.

    Returns:
        Path to the written file.
    """
    base = tmp_dir / "tool-results"
    date_dir = _ensure_date_dir(base)
    short = _short_hash(content)
    # Sanitise tool_name for use in a filename.
    safe_name = tool_name.replace("/", "_").replace(" ", "_")[:64]
    out_path = date_dir / f"{safe_name}_{short}.out"
    header = json.dumps({"tool": tool_name, "stored_at": _today_str(), **metadata})
    out_path.write_text(f"# {header}\n{content}", encoding="utf-8")
    return out_path


def store_shell_output(
    tmp_dir: Path,
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    duration_ms: int,
) -> Path:
    """Persist shell command output to ``{tmp_dir}/shell/YYYY-MM-DD/``.

    The file name is ``{cmd_short_hash}.log``.  A JSON header describing
    the invocation is prepended.

    Args:
        tmp_dir: Agent ``tmp/`` directory.
        command: Shell command that was executed.
        stdout: Standard output text.
        stderr: Standard error text (may be empty).
        exit_code: Process exit code.
        duration_ms: Execution duration in milliseconds.

    Returns:
        Path to the written file.
    """
    base = tmp_dir / "shell"
    date_dir = _ensure_date_dir(base)
    short = _short_hash(command)
    log_path = date_dir / f"{short}.log"
    header = json.dumps(
        {
            "command": command,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "stored_at": _today_str(),
        }
    )
    combined = f"# {header}\n"
    if stdout:
        combined += f"[stdout]\n{stdout}\n"
    if stderr:
        combined += f"[stderr]\n{stderr}\n"
    log_path.write_text(combined, encoding="utf-8")
    return log_path


def get_result(path: Path) -> str:
    """Read back a stored result from *path*.

    Args:
        path: Path previously returned by :func:`store_tool_result` or
            :func:`store_shell_output`.

    Returns:
        Full file content as a string.

    Raises:
        FileNotFoundError: If *path* does not exist.
    """
    return path.read_text(encoding="utf-8")


def rotate_results(
    tmp_dir: Path,
    retention_days: int,
    *,
    subtree: str | None = None,
) -> list[Path]:
    """Delete date directories older than *retention_days*.

    Args:
        tmp_dir: Agent ``tmp/`` directory.
        retention_days: Number of days to keep.  Directories whose date
            is strictly older than ``today - retention_days`` are removed.
        subtree: Which subdirectory to rotate.  ``"tool-results"`` or
            ``"shell"``; when ``None`` both are rotated.

    Returns:
        List of deleted directory paths.
    """
    cutoff: date = datetime.now(UTC).date() - timedelta(days=retention_days)
    deleted: list[Path] = []
    subtrees: tuple[Path, ...]
    if subtree is not None:
        subtrees = (tmp_dir / subtree,)
    else:
        subtrees = (tmp_dir / "tool-results", tmp_dir / "shell")
    for tree in subtrees:
        if not tree.is_dir():
            continue
        for date_dir in tree.iterdir():
            if not date_dir.is_dir():
                continue
            try:
                dir_date = date.fromisoformat(date_dir.name)
            except ValueError:
                continue  # skip non-date directories
            if dir_date < cutoff:
                shutil.rmtree(date_dir, ignore_errors=True)
                deleted.append(date_dir)
    return deleted
