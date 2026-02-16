"""Tests for exec_registry, pty_spawn, exec_tool, and process_tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import exec_registry
from exec_tool import execute, sandbox_cwd, validate_env
from models import AgentDeps, WorkItemType


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    exec_registry.reset()


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def mock_ctx(workspace: Path) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = MagicMock(spec=AgentDeps)
    ctx.deps.backend = MagicMock()
    ctx.deps.backend.root_dir = str(workspace)
    return ctx


# --- exec_registry ---


def test_add_and_get(workspace: Path) -> None:
    proc = MagicMock()
    session = exec_registry.ProcessSession(
        session_id="abc123",
        command="echo hi",
        process=proc,
        log_path=workspace / "test.log",
    )
    exec_registry.add(session)
    assert exec_registry.get("abc123") is session
    assert exec_registry.get("nope") is None


def test_list_sessions(workspace: Path) -> None:
    for i in range(3):
        proc = MagicMock()
        s = exec_registry.ProcessSession(
            session_id=f"s{i}",
            command=f"cmd{i}",
            process=proc,
            log_path=workspace / f"{i}.log",
            started_at=float(i),
        )
        exec_registry.add(s)
    sessions = exec_registry.list_sessions()
    assert [s.session_id for s in sessions] == ["s2", "s1", "s0"]


def test_mark_exited(workspace: Path) -> None:
    proc = MagicMock()
    session = exec_registry.ProcessSession(
        session_id="x1",
        command="ls",
        process=proc,
        log_path=workspace / "x.log",
        master_fd=None,
    )
    exec_registry.add(session)
    exec_registry.mark_exited("x1", 0)
    assert session.exit_code == 0
    assert session.finished_at is not None


def test_registry_can_be_replaced_for_injection(workspace: Path) -> None:
    proc = MagicMock()
    session = exec_registry.ProcessSession(
        session_id="isolated",
        command="echo isolated",
        process=proc,
        log_path=workspace / "isolated.log",
    )
    isolated_registry = exec_registry.ExecRegistry()
    previous = exec_registry.set_registry(isolated_registry)
    try:
        exec_registry.add(session)
        assert exec_registry.get("isolated") is session
    finally:
        exec_registry.set_registry(previous)


def test_cleanup_exec_logs(workspace: Path) -> None:
    log_dir = workspace / ".tmp" / "exec"
    log_dir.mkdir(parents=True)
    old_file = log_dir / "old.log"
    old_file.write_text("old")
    import os
    import time

    old_time = time.time() - 48 * 3600
    os.utime(old_file, (old_time, old_time))
    new_file = log_dir / "new.log"
    new_file.write_text("new")
    removed = exec_registry.cleanup_exec_logs(workspace, max_age_hours=24.0)
    assert removed == 1
    assert not old_file.exists()
    assert new_file.exists()


# --- exec_tool validation ---


def testvalidate_env_blocks_dangerous() -> None:
    with pytest.raises(ValueError, match="Blocked env vars"):
        validate_env(
            {
                "ANTHROPIC_API_KEY": "secret",
                "HOME": "/root",
                "LD_PRELOAD": "/tmp/libevil.so",
                "PYTHONPATH": "/tmp/evil",
            }
        )


def testvalidate_env_allows_safe() -> None:
    result = validate_env({"HOME": "/root", "PATH": "/usr/bin"})
    assert result == {"HOME": "/root", "PATH": "/usr/bin"}


def testsandbox_cwd_rejects_traversal(workspace: Path) -> None:
    with pytest.raises(ValueError, match="escapes workspace"):
        sandbox_cwd("../../etc", workspace)


def testsandbox_cwd_rejects_sibling_prefix_escape(workspace: Path) -> None:
    root = workspace / "work"
    root.mkdir()
    sibling = workspace / "work-escape"
    sibling.mkdir()
    with pytest.raises(ValueError, match="escapes workspace"):
        sandbox_cwd("../work-escape", root)


def testsandbox_cwd_allows_subdir(workspace: Path) -> None:
    sub = workspace / "sub"
    sub.mkdir()
    result = sandbox_cwd("sub", workspace)
    assert result == str(sub)


# --- exec_tool execute ---


@pytest.mark.asyncio()
async def test_execute_foreground(mock_ctx: MagicMock, workspace: Path) -> None:
    result = await execute(mock_ctx, "echo hello", timeout=10.0)
    assert result.metadata["exit_code"] == 0
    assert result.metadata["session_id"]
    assert "hello" in str(result.return_value)


@pytest.mark.asyncio()
async def test_execute_background(mock_ctx: MagicMock, workspace: Path) -> None:
    result = await execute(mock_ctx, "sleep 60", background=True, timeout=5.0)
    assert result.metadata["exit_code"] is None
    # Cleanup
    session = exec_registry.get(result.metadata["session_id"])
    assert session is not None
    session.process.kill()
    await session.process.wait()


@pytest.mark.asyncio()
async def test_execute_timeout(mock_ctx: MagicMock, workspace: Path) -> None:
    result = await execute(mock_ctx, "sleep 60", timeout=1.0)
    assert result.metadata["exit_code"] != 0  # killed


@pytest.mark.asyncio()
async def test_execute_omitted_env_filters_dangerous_vars(
    mock_ctx: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "leaked-openai-key")
    monkeypatch.setenv("PYTHONPATH", "/tmp/leaked-pythonpath")
    cmd = (
        "python3 -c "
        "'import os; "
        'print(os.getenv("OPENAI_API_KEY", "<missing>")); '
        'print(os.getenv("PYTHONPATH", "<missing>"))\''
    )
    result = await execute(mock_ctx, cmd, timeout=10.0)
    output = str(result.return_value)
    assert "<missing>" in output
    assert "leaked-openai-key" not in output
    assert "/tmp/leaked-pythonpath" not in output


# --- WorkItemType ---


def test_exec_callback_enum() -> None:
    assert WorkItemType.EXEC_CALLBACK == "exec_callback"
