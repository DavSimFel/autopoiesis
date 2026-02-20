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

All date-directories anywhere under ``tmp/`` are treated uniformly by
:func:`rotate_results`: first by age, then by total-size budget.

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


def _dir_size(path: Path) -> int:
    """Return total byte size of all files recursively under *path*."""
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _collect_date_dirs(tmp_dir: Path) -> list[tuple[date, Path]]:
    """Return all ``YYYY-MM-DD`` directories anywhere under *tmp_dir*, sorted oldest-first."""
    found: list[tuple[date, Path]] = []
    for candidate in tmp_dir.rglob("*"):
        if not candidate.is_dir():
            continue
        try:
            found.append((date.fromisoformat(candidate.name), candidate))
        except ValueError:
            pass
    found.sort(key=lambda t: t[0])
    return found


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
    max_size_mb: int,
) -> list[Path]:
    """Clean up ``tmp/`` by age then by size budget.

    All ``YYYY-MM-DD`` directories anywhere under *tmp_dir* are treated
    uniformly — no distinction between ``tool-results/`` and ``shell/``
    subtrees.

    Pass 1 — **age**: delete any date-dir strictly older than
    ``today - retention_days``.

    Pass 2 — **size**: if the surviving directories still exceed
    *max_size_mb* in total, delete the oldest remaining date-dirs first
    until the total is within budget.

    Args:
        tmp_dir: Agent ``tmp/`` directory.
        retention_days: Days to keep.
        max_size_mb: Size ceiling for all of ``tmp/`` in megabytes.

    Returns:
        List of deleted directory paths.
    """
    if not tmp_dir.is_dir():
        return []

    cutoff: date = datetime.now(UTC).date() - timedelta(days=retention_days)
    date_dirs = _collect_date_dirs(tmp_dir)  # oldest-first
    deleted: list[Path] = []

    # Pass 1: age-based eviction.
    surviving: list[tuple[date, Path]] = []
    for dir_date, dir_path in date_dirs:
        if dir_date < cutoff:
            shutil.rmtree(dir_path, ignore_errors=True)
            deleted.append(dir_path)
        else:
            surviving.append((dir_date, dir_path))

    # Pass 2: size-based eviction (oldest first).
    max_bytes = max_size_mb * 1024 * 1024
    total = sum(_dir_size(p) for _, p in surviving)
    for _, dir_path in surviving:
        if total <= max_bytes:
            break
        size = _dir_size(dir_path)
        shutil.rmtree(dir_path, ignore_errors=True)
        deleted.append(dir_path)
        total -= size

    return deleted
