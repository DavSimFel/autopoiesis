"""Process management tool for inspecting and controlling running sessions."""

from __future__ import annotations

import contextlib
import os
import signal
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn

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
) -> ToolReturn:
    """Poll a session for its current status and output tail.

    Args:
        session_id: Identifier of the session to poll.
    """
    session = _require_session(session_id)
    code = session.process.returncode
    if code is not None and session.exit_code is None:
        exec_registry.mark_exited(session_id, code)
    tail = _read_tail(session.log_path, 5)
    info = _session_info(session)
    tail_text = "\n".join(tail) if tail else "(no output)"
    return ToolReturn(return_value=tail_text, metadata={**info, "session_id": session_id})


async def process_log(
    ctx: RunContext[AgentDeps],
    session_id: str,
    *,
    offset: int = 0,
    limit: int = 50,
) -> ToolReturn:
    """Read log lines from a session's output file.

    Args:
        session_id: Identifier of the session to read logs from.
        offset: Line offset to start reading from.
        limit: Maximum number of lines to return.
    """
    session = _require_session(session_id)
    try:
        text = session.log_path.read_text(errors="replace")
    except OSError:
        return ToolReturn(
            return_value="(no log output)",
            metadata={"session_id": session_id, "log_path": str(session.log_path), "total": 0},
        )
    all_lines = text.splitlines()
    selected = all_lines[offset : offset + limit]
    content = "\n".join(selected) if selected else "(empty)"
    return ToolReturn(
        return_value=content,
        metadata={
            "session_id": session_id,
            "log_path": str(session.log_path),
            "total": len(all_lines),
        },
    )


async def process_write(
    ctx: RunContext[AgentDeps],
    session_id: str,
    data: str,
) -> ToolReturn:
    """Write data to a session's stdin.

    Args:
        session_id: Identifier of the session to write to.
        data: String data to send to the session's stdin.
    """
    session = _require_session(session_id)
    if session.process.stdin is None:
        msg = "Session has no stdin (PTY sessions use send_keys)"
        raise ValueError(msg)
    session.process.stdin.write(data.encode())
    await session.process.stdin.drain()
    return ToolReturn(return_value="written", metadata={"session_id": session_id})


async def process_send_keys(
    ctx: RunContext[AgentDeps],
    session_id: str,
    data: str,
) -> ToolReturn:
    """Send keystrokes to a PTY session's master fd.

    Args:
        session_id: Identifier of the PTY session.
        data: Keystroke data to send to the PTY master.
    """
    session = _require_session(session_id)
    if session.master_fd is None or session.master_fd < 0:
        msg = "Session has no PTY master fd"
        raise ValueError(msg)
    os.write(session.master_fd, data.encode())
    return ToolReturn(return_value="sent", metadata={"session_id": session_id})


async def process_kill(
    ctx: RunContext[AgentDeps],
    session_id: str,
    *,
    sig: int = signal.SIGTERM,
) -> ToolReturn:
    """Kill a running session.

    Args:
        session_id: Identifier of the session to kill.
        sig: Signal number to send (default: SIGTERM).
    """
    session = _require_session(session_id)
    if session.exit_code is not None:
        return ToolReturn(
            return_value="already_exited",
            metadata={**_session_info(session), "session_id": session_id},
        )
    with contextlib.suppress(ProcessLookupError):
        session.process.send_signal(sig)
    code = await session.process.wait()
    exec_registry.mark_exited(session_id, code)
    return ToolReturn(
        return_value="killed",
        metadata={**_session_info(session), "session_id": session_id},
    )


def _read_tail(path: Path, n: int) -> list[str]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if len(lines) > n else lines
