"""In-memory registry for tracked subprocess sessions.

Dependencies: (stdlib only)
Wired in: tools/exec_tool.py, tools/process_tool.py, toolset_builder.py → build_toolsets()
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


@dataclass
class ProcessSession:
    """Tracked subprocess session with metadata."""

    session_id: str
    command: str
    process: asyncio.subprocess.Process
    log_path: Path
    started_at: float = field(default_factory=time.time)
    master_fd: int | None = None
    exit_code: int | None = None
    finished_at: float | None = None
    background: bool = False


class ExecRegistry:
    """Thread-safe in-memory registry of subprocess sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, ProcessSession] = {}
        self._lock = threading.Lock()

    def add(self, session: ProcessSession) -> None:
        """Register a session."""
        with self._lock:
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> ProcessSession | None:
        """Retrieve a session by id."""
        with self._lock:
            return self._sessions.get(session_id)

    def list_sessions(self) -> list[ProcessSession]:
        """Return all tracked sessions (newest first)."""
        with self._lock:
            sessions = list(self._sessions.values())
        return sorted(sessions, key=lambda s: s.started_at, reverse=True)

    def mark_exited(self, session_id: str, exit_code: int) -> None:
        """Record process exit."""
        master_fd: int | None = None
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.exit_code = exit_code
            session.finished_at = time.time()
            if session.master_fd is not None and session.master_fd >= 0:
                master_fd = session.master_fd
                session.master_fd = None
        if master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(master_fd)

    def reset(self) -> None:
        """Clear all sessions."""
        with self._lock:
            self._sessions.clear()


_registry = ExecRegistry()


def get_registry() -> ExecRegistry:
    """Return the active process-session registry."""
    return _registry


def set_registry(registry: ExecRegistry) -> ExecRegistry:
    """Replace the active process-session registry and return the previous one."""
    global _registry
    previous = _registry
    _registry = registry
    return previous


def _log_dir(workspace_root: Path) -> Path:
    d = workspace_root / ".tmp" / "exec"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_session_id() -> str:
    """Generate a short unique session id."""
    return uuid4().hex[:12]


def add(session: ProcessSession) -> None:
    """Register a session."""
    _registry.add(session)


def get(session_id: str) -> ProcessSession | None:
    """Retrieve a session by id."""
    return _registry.get(session_id)


def list_sessions() -> list[ProcessSession]:
    """Return all tracked sessions (newest first)."""
    return _registry.list_sessions()


def mark_exited(session_id: str, exit_code: int) -> None:
    """Record process exit."""
    _registry.mark_exited(session_id, exit_code)


def cleanup_exec_logs(workspace_root: Path, *, max_age_hours: float = 24.0) -> int:
    """Remove log files older than *max_age_hours*. Returns count removed."""
    log_dir = _log_dir(workspace_root)
    if not log_dir.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for entry in log_dir.iterdir():
        if entry.is_file() and entry.stat().st_mtime < cutoff:
            entry.unlink(missing_ok=True)
            removed += 1
    return removed


def log_path_for(workspace_root: Path, session_id: str) -> Path:
    """Return the log file path for a given session."""
    return _log_dir(workspace_root) / f"{session_id}.log"


def reset() -> None:
    """Clear all sessions (testing only)."""
    _registry.reset()
