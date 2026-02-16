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

    When to use: To check what background processes are active, find session IDs
    for polling or interaction, or verify a process has started.
    Returns: List of dicts, each with session_id, command, pid, exit_code (null if
    still running), and background flag.
    Related: process_poll (check one session in detail), execute (start new process).
    """
    return [_session_info(s) for s in exec_registry.list_sessions()]


async def process_poll(
    ctx: RunContext[AgentDeps],
    session_id: str,
) -> dict[str, Any]:
    """Check a specific session's current status and recent output.

    When to use: After starting a background process, to check if it has finished
    and see its latest output. Lighter than process_log when you just need a status check.
    Returns: Session info dict plus output_tail (last 5 lines of output).
    Related: process_log (read full output with pagination), process_list (find session IDs).

    Args:
        session_id: The session ID returned by execute or execute_pty.
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
    """Read log lines from a session's output file with pagination.

    When to use: When process_poll's 5-line tail isn't enough and you need to see
    more output — full build logs, error tracebacks, test results, etc.
    Returns: Dict with session_id, lines (list of strings), and total line count.
    Related: process_poll (quick status + tail), execute (start process).

    Args:
        session_id: The session ID to read logs from.
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
    """Write data to a non-PTY session's stdin pipe.

    When to use: To send input to a running subprocess that reads from stdin (e.g.,
    answering a prompt, piping data). For PTY sessions, use process_send_keys instead.
    Returns: Confirmation dict with status and session_id.
    Related: process_send_keys (for PTY sessions), execute (start non-PTY process).

    Args:
        session_id: The session to write to.
        data: String data to write to stdin. Include '\\n' for newlines/Enter.
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
    """Send keystrokes to a PTY session (interactive terminal input).

    When to use: To type into an interactive PTY session — answering prompts, sending
    commands to a REPL, navigating terminal UIs. Only works with sessions started via
    execute_pty. For non-PTY sessions, use process_write instead.
    Returns: Confirmation dict with status and session_id.
    Related: process_write (for non-PTY stdin), execute_pty (start PTY session),
    process_log (read what the PTY printed back).

    Args:
        session_id: The PTY session to send keystrokes to.
        data: Keystrokes as a string. Use '\\r' for Enter, '\\x03' for Ctrl-C,
            '\\x04' for Ctrl-D, '\\x1b' for Escape.
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

    When to use: To stop a background process that is no longer needed, hung, or
    misbehaving. Also useful for cleaning up servers or watchers after testing.
    Returns: Dict with status ('killed' or 'already_exited') and session info.
    Related: process_list (find sessions to kill), execute (start new process).

    Args:
        session_id: The session to terminate.
        sig: Unix signal number to send. Default SIGTERM (15) for graceful shutdown.
            Use 9 (SIGKILL) for force-kill of unresponsive processes.
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
