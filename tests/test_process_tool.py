"""Tests for process_tool: poll, write, kill via mocked exec_registry."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from pydantic_ai.messages import ToolReturn

import exec_registry
from models import AgentDeps
from process_tool import process_kill, process_list, process_poll, process_write


def _fake_process(
    *,
    returncode: int | None = None,
    pid: int = 1234,
    stdin: Any = None,
) -> asyncio.subprocess.Process:
    proc = MagicMock(spec=asyncio.subprocess.Process)
    proc.returncode = returncode
    proc.pid = pid
    proc.stdin = stdin
    proc.send_signal = MagicMock()
    proc.wait = AsyncMock(return_value=returncode if returncode is not None else 0)
    return proc  # type: ignore[no-any-return]


def _make_session(
    tmp_path: Path,
    *,
    session_id: str = "abc123",
    returncode: int | None = None,
    background: bool = True,
    stdin: Any = None,
    log_content: str = "",
) -> exec_registry.ProcessSession:
    log_path = tmp_path / f"{session_id}.log"
    log_path.write_text(log_content)
    proc = _fake_process(returncode=returncode, stdin=stdin)
    session = exec_registry.ProcessSession(
        session_id=session_id,
        command="echo hello",
        process=proc,
        log_path=log_path,
        background=background,
    )
    exec_registry.add(session)
    return session


def _mock_ctx(mock_deps: AgentDeps) -> Any:
    ctx = MagicMock()
    ctx.deps = mock_deps
    return ctx


def _reset_registry() -> None:
    exec_registry.reset()


async def test_process_list_empty(mock_deps: AgentDeps) -> None:
    _reset_registry()
    result = await process_list(_mock_ctx(mock_deps))
    assert result == []


async def test_process_list_returns_sessions(mock_deps: AgentDeps, tmp_path: Path) -> None:
    _reset_registry()
    _make_session(tmp_path, session_id="s1")
    _make_session(tmp_path, session_id="s2")
    result = await process_list(_mock_ctx(mock_deps))
    expected_count = 2
    assert len(result) == expected_count
    ids = {r["session_id"] for r in result}
    assert ids == {"s1", "s2"}


async def test_process_poll_running(mock_deps: AgentDeps, tmp_path: Path) -> None:
    _reset_registry()
    _make_session(tmp_path, log_content="line1\nline2\nline3\n")
    result = await process_poll(_mock_ctx(mock_deps), "abc123")
    assert isinstance(result, ToolReturn)
    assert isinstance(result.return_value, str)
    assert "line" in result.return_value


async def test_process_poll_marks_exited(mock_deps: AgentDeps, tmp_path: Path) -> None:
    _reset_registry()
    session = _make_session(tmp_path, returncode=0, log_content="done\n")
    await process_poll(_mock_ctx(mock_deps), "abc123")
    assert session.exit_code == 0


async def test_process_poll_unknown_session(mock_deps: AgentDeps) -> None:
    _reset_registry()
    try:
        await process_poll(_mock_ctx(mock_deps), "nonexistent")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "Unknown session" in str(exc)


async def test_process_write_sends_data(mock_deps: AgentDeps, tmp_path: Path) -> None:
    _reset_registry()
    stdin_mock = AsyncMock()
    stdin_mock.write = MagicMock()
    stdin_mock.drain = AsyncMock()
    _make_session(tmp_path, stdin=stdin_mock)
    result = await process_write(_mock_ctx(mock_deps), "abc123", "hello\n")
    assert isinstance(result, ToolReturn)
    assert result.return_value == "written"
    stdin_mock.write.assert_called_once_with(b"hello\n")
    stdin_mock.drain.assert_awaited_once()


async def test_process_write_no_stdin_raises(mock_deps: AgentDeps, tmp_path: Path) -> None:
    _reset_registry()
    _make_session(tmp_path, stdin=None)
    try:
        await process_write(_mock_ctx(mock_deps), "abc123", "data")
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "no stdin" in str(exc)


async def test_process_kill_running(mock_deps: AgentDeps, tmp_path: Path) -> None:
    _reset_registry()
    session = _make_session(tmp_path)
    result = await process_kill(_mock_ctx(mock_deps), "abc123")
    assert isinstance(result, ToolReturn)
    assert result.return_value == "killed"
    mock_proc = session.process
    assert isinstance(mock_proc.send_signal, MagicMock)
    mock_proc.send_signal.assert_called_once()


async def test_process_kill_already_exited(mock_deps: AgentDeps, tmp_path: Path) -> None:
    _reset_registry()
    session = _make_session(tmp_path, returncode=0)
    session.exit_code = 0
    result = await process_kill(_mock_ctx(mock_deps), "abc123")
    assert isinstance(result, ToolReturn)
    assert result.return_value == "already_exited"
