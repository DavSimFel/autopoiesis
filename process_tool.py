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
    """List all tracked process sessions (running and exited).

    Use to discover active background processes or check what commands have been run.
    Returns session_id, command, pid, exit_code, and background flag for each session.
    Call this before process_poll or process_log to find the right session_id.
    """
    return [_session_info(s) for s in exec_registry.list_sessions()]


async def process_poll(
    ctx: RunContext[AgentDeps],
    session_id: str,
) -> dict[str, Any]:
    """Check the current status of a process session.

    Use to monitor background processes: returns whether the process is still running,
    its exit code (if finished), and the last 5 lines of output. Call repeatedly to
    watch long-running commands.

    Args:
        session_id: The session identifier returned by execute or execute_pty.
    """
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
    """Read output lines from a process session's log file.

    Use to inspect full command output beyond the tail summary. Supports pagination
    via offset and limit for large outputs (e.g. test results, build logs).

    Args:
        session_id: The session identifier.
        offset: Line number to start reading from (0-indexed). Default 0.
        limit: Maximum number of lines to return. Default 50.
    """
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
    """Write data to a non-PTY session's standard input.

    Use for piping input to processes started with execute (not execute_pty).
    For PTY sessions, use process_send_keys instead. Requires user approval.

    Args:
        session_id: The session identifier.
        data: Text to write to stdin. Include newlines as needed (e.g. "yes\\n").
    """
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
    """Send keystrokes to a PTY session.

    Use for interactive programs started with execute_pty. Sends raw bytes to the
    terminal, supporting control characters (e.g. "\\x03" for Ctrl-C, "\\n" for Enter).
    For non-PTY sessions, use process_write instead. Requires user approval.

    Args:
        session_id: The session identifier (must be a PTY session).
        data: Text or control characters to send to the terminal.
    """
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
    """Terminate a running process session.

    Use to stop a background process or kill a hung command. Sends SIGTERM by default
    (graceful shutdown); use sig=9 (SIGKILL) for forceful termination. Requires user approval.

    Args:
        session_id: The session identifier.
        sig: Signal number to send. Default is SIGTERM (15). Use 9 for SIGKILL.
    """
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
