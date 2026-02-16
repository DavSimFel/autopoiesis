"""Shell execution tool for the agent runtime.

Spawns commands with optional PTY support, timeout, and background mode.
Full output is written to a log file; only a summary is returned.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext

import exec_registry
from models import AgentDeps
from pty_spawn import PtyProcess, read_master, spawn_pty

_background_tasks: set[asyncio.Task[None]] = set()

_DANGEROUS_ENV_VARS: frozenset[str] = frozenset(
    {
        "AWS_SECRET_ACCESS_KEY",
        "DATABASE_URL",
        "DB_PASSWORD",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "SECRET_KEY",
        "PRIVATE_KEY",
        "PASSWORD",
    }
)

_DEFAULT_TIMEOUT: float = 30.0
_MAX_SUMMARY_LINES: int = 5


def validate_env(env: dict[str, str] | None) -> dict[str, str] | None:
    if env is None:
        return None
    blocked = _DANGEROUS_ENV_VARS & env.keys()
    if blocked:
        msg = f"Blocked env vars: {', '.join(sorted(blocked))}"
        raise ValueError(msg)
    return env


def sandbox_cwd(cwd: str | None, workspace_root: Path) -> str:
    """Resolve and validate the working directory stays inside workspace."""
    if cwd is None:
        return str(workspace_root)
    resolved = (workspace_root / cwd).resolve()
    if not str(resolved).startswith(str(workspace_root.resolve())):
        msg = f"Working directory escapes workspace: {cwd}"
        raise ValueError(msg)
    return str(resolved)


def _tail_lines(path: Path, n: int) -> list[str]:
    """Return the last *n* lines from a file."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if len(lines) > n else lines


async def _read_pty_output(pty_proc: PtyProcess, log_path: Path) -> None:
    """Drain PTY master fd to log file until EOF."""
    loop = asyncio.get_running_loop()
    with log_path.open("ab") as f:
        while True:
            try:
                data = await loop.run_in_executor(None, read_master, pty_proc.master_fd)
            except OSError:
                break
            if not data:
                break
            f.write(data)


async def _spawn_pty_session(
    command: str,
    cwd: str,
    env: dict[str, str] | None,
    log_path: Path,
) -> tuple[asyncio.subprocess.Process, int]:
    """Spawn a command under a PTY and return (process, master_fd)."""
    pty_proc = await spawn_pty(command, cwd=cwd, env=env)
    # Start draining output in background
    task = asyncio.create_task(_read_pty_output(pty_proc, log_path))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return pty_proc.process, pty_proc.master_fd


async def _close_fh_on_exit(
    proc: asyncio.subprocess.Process,
    log_fh: Any,
) -> None:
    """Wait for *proc* to exit, then close the log file handle."""
    await proc.wait()
    log_fh.close()


def _enqueue_exit_callback(session: exec_registry.ProcessSession) -> None:
    """Enqueue a HIGH-priority work item with exit details."""
    from chat_worker import enqueue
    from models import WorkItem, WorkItemInput, WorkItemPriority, WorkItemType

    tail = _tail_lines(session.log_path, _MAX_SUMMARY_LINES)
    item = WorkItem(
        type=WorkItemType.EXEC_CALLBACK,
        priority=WorkItemPriority.HIGH,
        input=WorkItemInput(prompt=None),
        payload={
            "session_id": session.session_id,
            "exit_code": session.exit_code,
            "log_path": str(session.log_path),
            "output_tail": tail,
        },
    )
    enqueue(item)


async def _monitor_background(session: exec_registry.ProcessSession) -> None:
    """Wait for a background process to exit, then record and notify."""
    code = await session.process.wait()
    exec_registry.mark_exited(session.session_id, code)
    _enqueue_exit_callback(session)


async def _spawn_subprocess(
    command: str,
    cwd: str,
    env: dict[str, str] | None,
    log_path: Path,
) -> tuple[asyncio.subprocess.Process, None]:
    """Spawn a command as a plain subprocess."""
    log_fh = log_path.open("wb")
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=log_fh,
        stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    # Ensure the file handle is closed when the process exits.
    task = asyncio.create_task(_close_fh_on_exit(proc, log_fh))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return proc, None


def _build_summary(session: exec_registry.ProcessSession) -> dict[str, Any]:
    tail = _tail_lines(session.log_path, _MAX_SUMMARY_LINES)
    return {
        "session_id": session.session_id,
        "command": session.command,
        "exit_code": session.exit_code,
        "log_path": str(session.log_path),
        "output_tail": tail,
        "background": session.background,
    }


async def _wait_with_timeout(
    session: exec_registry.ProcessSession,
    timeout: float,
) -> dict[str, Any]:
    """Wait for the process to finish within *timeout*, kill if exceeded."""
    try:
        code = await asyncio.wait_for(session.process.wait(), timeout=timeout)
    except TimeoutError:
        session.process.kill()
        code = await session.process.wait()
    exec_registry.mark_exited(session.session_id, code)
    return _build_summary(session)


async def execute(
    ctx: RunContext[AgentDeps],
    command: str,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    background: bool = False,
) -> dict[str, Any]:
    """Run a shell command as a plain subprocess (no TTY).

    When to use: For any non-interactive shell command — running scripts, installing
    packages, git operations, file manipulation, builds, tests, linters, etc. Use
    execute_pty instead if the program requires a terminal (e.g. vim, top, interactive
    REPLs). Set background=True for long-running servers or watch commands.
    Returns: Dict with session_id, command, exit_code (null if background), log_path,
    output_tail (last 5 lines of stdout+stderr), and background flag.
    Related: execute_pty (interactive/TTY programs), process_list (find running sessions),
    process_log (read full output), process_kill (stop background processes).

    Args:
        command: Shell command string (passed to /bin/sh -c). Pipe, redirect, && all work.
        cwd: Working directory relative to workspace root. Must stay inside workspace.
            Omit to use workspace root.
        env: Extra environment variables as key-value pairs. Security-sensitive keys
            (API keys, passwords, tokens) are blocked and will raise an error.
        timeout: Maximum seconds to wait before killing the process (foreground only).
            Default 30. Ignored when background=True.
        background: If True, start the process and return immediately with session_id.
            Use process_poll/process_log to check on it later. A notification is
            enqueued automatically when the background process exits.
    """
    workspace_root = Path(ctx.deps.backend.root_dir)
    safe_cwd = sandbox_cwd(cwd, workspace_root)
    safe_env = validate_env(env)
    session_id = exec_registry.new_session_id()
    log_path = exec_registry.log_path_for(workspace_root, session_id)

    proc, master_fd = await _spawn_subprocess(command, safe_cwd, safe_env, log_path)

    session = exec_registry.ProcessSession(
        session_id=session_id,
        command=command,
        process=proc,
        log_path=log_path,
        master_fd=master_fd,
        background=background,
    )
    exec_registry.add(session)

    if background:
        task = asyncio.create_task(_monitor_background(session))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return _build_summary(session)
    return await _wait_with_timeout(session, timeout)


async def execute_pty(
    ctx: RunContext[AgentDeps],
    command: str,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    background: bool = False,
) -> dict[str, Any]:
    """Run a shell command under a pseudo-terminal (PTY) for interactive programs.

    When to use: When the program requires a TTY — interactive REPLs (python, node),
    terminal UIs (vim, htop, less), or commands that detect terminal absence and change
    behavior (e.g. colored output, progress bars). For simple non-interactive commands,
    prefer execute (lower overhead).
    Returns: Same dict as execute: session_id, command, exit_code, log_path, output_tail.
    Related: execute (non-interactive commands), process_send_keys (type into PTY session),
    process_poll (check session status), process_log (read PTY output).

    Args:
        command: Shell command string to run under a PTY.
        cwd: Working directory relative to workspace root. Must stay inside workspace.
        env: Extra environment variables (security-sensitive keys blocked).
        timeout: Max seconds before killing (foreground only). Default 30.
        background: If True, return immediately. Use process_send_keys to interact
            and process_log to read output.
    """
    workspace_root = Path(ctx.deps.backend.root_dir)
    safe_cwd = sandbox_cwd(cwd, workspace_root)
    safe_env = validate_env(env)
    session_id = exec_registry.new_session_id()
    log_path = exec_registry.log_path_for(workspace_root, session_id)

    proc, master_fd = await _spawn_pty_session(command, safe_cwd, safe_env, log_path)

    session = exec_registry.ProcessSession(
        session_id=session_id,
        command=command,
        process=proc,
        log_path=log_path,
        master_fd=master_fd,
        background=background,
    )
    exec_registry.add(session)

    if background:
        task = asyncio.create_task(_monitor_background(session))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return _build_summary(session)
    return await _wait_with_timeout(session, timeout)
