"""Process management tool for inspecting and controlling running sessions.

Dependencies: infra.exec_registry, io_utils, models
Wired in: toolset_builder.py → build_toolsets()
"""

from __future__ import annotations

import contextlib
import os
import signal
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn

from infra import exec_registry
from io_utils import tail_lines
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
    """List all running and recently exited background process sessions."""
    return [_session_info(s) for s in exec_registry.list_sessions()]


async def process_poll(
    ctx: RunContext[AgentDeps],
    session_id: str,
) -> ToolReturn:
    """Check if a background process is still running and get its latest output.

    Args:
        session_id: Session id returned by execute or execute_pty.
    """
    session = _require_session(session_id)
    code = session.process.returncode
    if code is not None and session.exit_code is None:
        exec_registry.mark_exited(session_id, code)
    tail = tail_lines(session.log_path, 5)
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
    """Read output from a background process log.

    Use to review full output or paginate through logs.

    Args:
        session_id: Session id to read logs from.
        offset: Line number to start from (0-indexed).
        limit: Maximum lines to return. Default 50.
    """
    session = _require_session(session_id)
    try:
        total = _count_lines(session.log_path)
        start, stop, _ = slice(offset, offset + limit).indices(total)
        selected = _read_line_slice(session.log_path, start, stop)
    except OSError:
        return ToolReturn(
            return_value="(no log output)",
            metadata={"session_id": session_id, "log_path": str(session.log_path), "total": 0},
        )
    content = "\n".join(selected) if selected else "(empty)"
    return ToolReturn(
        return_value=content,
        metadata={
            "session_id": session_id,
            "log_path": str(session.log_path),
            "total": total,
        },
    )


async def process_write(
    ctx: RunContext[AgentDeps],
    session_id: str,
    data: str,
) -> ToolReturn:
    """Send text to a non-PTY process via stdin. For PTY sessions, use process_send_keys instead.

    Args:
        session_id: Session id of the running process.
        data: Text to write to the process stdin.
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
    """Send keystrokes to an interactive PTY session.

    Use for answering prompts, navigating TUIs, or control sequences.

    Args:
        session_id: Session id of a PTY process (started with execute_pty).
        data: Keystroke data to send (e.g. "y\\n" for yes+enter, "\\x03" for Ctrl-C).
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
    """Terminate a running background process.

    Use when a process is stuck, no longer needed, or timed out.

    Args:
        session_id: Session id of the process to kill.
        sig: Unix signal number. Default SIGTERM (graceful). Use 9 for SIGKILL (force).
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


def _count_lines(path: Path) -> int:
    with path.open("rb") as log_file:
        return sum(1 for _ in log_file)


def _read_line_slice(path: Path, start: int, stop: int) -> list[str]:
    if stop <= start:
        return []
    selected: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as log_file:
        for line_index, raw_line in enumerate(log_file):
            if line_index >= stop:
                break
            if line_index >= start:
                selected.append(raw_line.rstrip("\r\n"))
    return selected
