"""Process management tool for inspecting and controlling running sessions."""

from __future__ import annotations

import contextlib
import os
import signal
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext

import exec_registry
from models import AgentDeps


def _session_info(s: exec_registry.ProcessSession) -> dict[str, Any]:
    return {
        "session_id": s.session_id,
        "command": s.command,
        "pid": s.process.pid,
        "exit_code": s.exit_code,
        "background": s.background,
    }


def _require_session(session_id: str) -> exec_registry.ProcessSession:
    session = exec_registry.get(session_id)
    if session is None:
        msg = f"Unknown session: {session_id}"
        raise ValueError(msg)
    return session


async def process_list(
    ctx: RunContext[AgentDeps],
) -> list[dict[str, Any]]:
    """List all tracked process sessions."""
    return [_session_info(s) for s in exec_registry.list_sessions()]


async def process_poll(
    ctx: RunContext[AgentDeps],
    session_id: str,
) -> dict[str, Any]:
    """Poll a session for its current status and output tail."""
    session = _require_session(session_id)
    code = session.process.returncode
    if code is not None and session.exit_code is None:
        exec_registry.mark_exited(session_id, code)
    tail = _read_tail(session.log_path, 5)
    return {**_session_info(session), "output_tail": tail}


async def process_log(
    ctx: RunContext[AgentDeps],
    session_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Read log lines from a session's output file."""
    session = _require_session(session_id)
    try:
        text = session.log_path.read_text(errors="replace")
    except OSError:
        return {"session_id": session_id, "lines": [], "total": 0}
    all_lines = text.splitlines()
    selected = all_lines[offset : offset + limit]
    return {"session_id": session_id, "lines": selected, "total": len(all_lines)}


async def process_write(
    ctx: RunContext[AgentDeps],
    session_id: str,
    data: str,
) -> dict[str, str]:
    """Write data to a session's stdin."""
    session = _require_session(session_id)
    if session.process.stdin is None:
        msg = "Session has no stdin (PTY sessions use send_keys)"
        raise ValueError(msg)
    session.process.stdin.write(data.encode())
    await session.process.stdin.drain()
    return {"status": "written", "session_id": session_id}


async def process_send_keys(
    ctx: RunContext[AgentDeps],
    session_id: str,
    data: str,
) -> dict[str, str]:
    """Send keystrokes to a PTY session's master fd."""
    session = _require_session(session_id)
    if session.master_fd is None or session.master_fd < 0:
        msg = "Session has no PTY master fd"
        raise ValueError(msg)
    os.write(session.master_fd, data.encode())
    return {"status": "sent", "session_id": session_id}


async def process_kill(
    ctx: RunContext[AgentDeps],
    session_id: str,
    *,
    sig: int = signal.SIGTERM,
) -> dict[str, Any]:
    """Kill a running session."""
    session = _require_session(session_id)
    if session.exit_code is not None:
        return {"status": "already_exited", **_session_info(session)}
    with contextlib.suppress(ProcessLookupError):
        session.process.send_signal(sig)
    code = await session.process.wait()
    exec_registry.mark_exited(session_id, code)
    return {"status": "killed", **_session_info(session)}


def _read_tail(path: Path, n: int) -> list[str]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if len(lines) > n else lines
