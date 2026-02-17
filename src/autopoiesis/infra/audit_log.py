"""Append-only audit log for shell commands (Issue #170)."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autopoiesis.tools.shell_tool import ShellResult


def log_command(command: str, result: ShellResult, audit_path: Path) -> None:
    """Append a command execution record to the audit log."""
    ts = datetime.datetime.now(tz=datetime.UTC).isoformat()
    entry = (
        f"[{ts}] command={command!r} exit_code={result.exit_code} timed_out={result.timed_out}\n"
    )
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a") as f:
        f.write(entry)
