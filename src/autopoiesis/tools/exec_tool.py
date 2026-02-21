"""Shell execution tool: PTY, timeout, background mode; persists output via result_store."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn

from autopoiesis.infra import exec_registry
from autopoiesis.infra.pty_spawn import PtyProcess, read_master, spawn_pty
from autopoiesis.io_utils import tail_lines
from autopoiesis.models import AgentDeps
from autopoiesis.security.subprocess_sandbox import SubprocessSandboxManager
from autopoiesis.store.result_store import store_shell_output
from autopoiesis.tools.tier_enforcement import enforce_tier

_log = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task[None]] = set()

_DANGEROUS_ENV_VARS: frozenset[str] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "DATABASE_URL",
        "DB_PASSWORD",
        "GITHUB_TOKEN",
        "LD_PRELOAD",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "PASSWORD",
        "PRIVATE_KEY",
        "PYTHONPATH",
        "SECRET_KEY",
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


def resolve_env(env: dict[str, str] | None) -> dict[str, str]:
    """Return a subprocess env with dangerous inherited variables removed."""
    safe_env = validate_env(env)
    if safe_env is not None:
        return safe_env
    return {k: v for k, v in os.environ.items() if k not in _DANGEROUS_ENV_VARS}


def sandbox_cwd(cwd: str | None, workspace_root: Path) -> str:
    """Resolve and validate the working directory stays inside workspace."""
    sandbox = SubprocessSandboxManager(workspace_root=workspace_root)
    try:
        return str(sandbox.resolve_cwd(cwd))
    except ValueError as exc:
        raise ValueError(f"Working directory escapes workspace: {cwd}") from exc


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
    sandbox: SubprocessSandboxManager,
) -> tuple[asyncio.subprocess.Process, int]:
    """Spawn a command under a PTY and return (process, master_fd)."""
    pty_proc = await spawn_pty(command, cwd=cwd, env=env, preexec_fn=sandbox.preexec_fn())
    # Start draining output in background
    task = asyncio.create_task(_read_pty_output(pty_proc, log_path))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return pty_proc.process, pty_proc.master_fd


async def _monitor_background(session: exec_registry.ProcessSession) -> None:
    """Wait for background exit, record it, then enqueue callback work item."""
    from autopoiesis.agent.worker import enqueue
    from autopoiesis.models import WorkItem, WorkItemInput, WorkItemPriority, WorkItemType

    code = await session.process.wait()
    exec_registry.mark_exited(session.session_id, code)
    tail = tail_lines(session.log_path, _MAX_SUMMARY_LINES)
    enqueue(
        WorkItem(
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
    )


async def _spawn_subprocess(
    command: str,
    cwd: str,
    env: dict[str, str] | None,
    log_path: Path,
    sandbox: SubprocessSandboxManager,
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
        preexec_fn=sandbox.preexec_fn(),
    )

    async def _close_fh() -> None:
        await proc.wait()
        log_fh.close()

    task = asyncio.create_task(_close_fh())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return proc, None


def _to_tool_return(summary: dict[str, Any]) -> ToolReturn:
    """Convert a summary dict into a ToolReturn with structured metadata."""
    tail = summary.get("output_tail", [])
    content = "\n".join(tail) if tail else "(no output)"
    return ToolReturn(
        return_value=content,
        metadata={
            "session_id": summary["session_id"],
            "log_path": summary.get("log_path", ""),
            "exit_code": summary.get("exit_code"),
        },
    )


def _build_summary(session: exec_registry.ProcessSession) -> dict[str, Any]:
    tail = tail_lines(session.log_path, _MAX_SUMMARY_LINES)
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


async def _finish_session(
    session: exec_registry.ProcessSession,
    timeout: float,
    tmp_dir: Path | None = None,
    start_time: float | None = None,
) -> ToolReturn:
    """Register a session; persist foreground output to ``{tmp_dir}/shell/``."""
    exec_registry.add(session)
    if session.background:
        task = asyncio.create_task(_monitor_background(session))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        summary = _build_summary(session)
    else:
        summary = await _wait_with_timeout(session, timeout)
        if tmp_dir is not None and start_time is not None:
            try:
                combined = session.log_path.read_text(encoding="utf-8", errors="replace")
                store_shell_output(
                    tmp_dir=tmp_dir,
                    command=session.command,
                    stdout=combined,
                    stderr="",
                    exit_code=session.exit_code or 0,
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )
            except OSError:
                _log.debug("store_shell_output failed for %s", session.session_id)
    return _to_tool_return(summary)


async def _run_exec(  # noqa: PLR0913
    ctx: RunContext[AgentDeps],
    command: str,
    cwd: str | None,
    env: dict[str, str] | None,
    timeout: float,
    background: bool,
    *,
    pty: bool = False,
) -> ToolReturn:
    """Shared body for execute and execute_pty."""
    blocked = enforce_tier(command, ctx.deps.approval_unlocked)
    if blocked is not None:
        return blocked
    workspace_root = Path(ctx.deps.backend.root_dir)
    sandbox = SubprocessSandboxManager(workspace_root=workspace_root)
    safe_cwd = str(sandbox.resolve_cwd(cwd))
    safe_env = resolve_env(env)
    session_id = exec_registry.new_session_id()
    log_path = exec_registry.log_path_for(workspace_root, session_id)
    start_time = time.monotonic()
    spawner = _spawn_pty_session if pty else _spawn_subprocess
    proc, master_fd = await spawner(command, safe_cwd, safe_env, log_path, sandbox)
    session = exec_registry.ProcessSession(
        session_id=session_id,
        command=command,
        process=proc,
        log_path=log_path,
        master_fd=master_fd,
        background=background,
    )
    return await _finish_session(
        session, timeout, tmp_dir=workspace_root / "tmp", start_time=start_time
    )


async def execute(
    ctx: RunContext[AgentDeps],
    command: str,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    background: bool = False,
) -> ToolReturn:
    """Run a shell command in the workspace.

    Args:
        command: Shell command to run (e.g. "pytest -q", "git status").
        cwd: Working directory relative to workspace root.
        env: Extra environment variables. Dangerous keys are blocked.
        timeout: Seconds before kill (foreground only).
        background: Return immediately with a session id for monitoring.
    """
    return await _run_exec(ctx, command, cwd, env, timeout, background)


async def execute_pty(
    ctx: RunContext[AgentDeps],
    command: str,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    background: bool = False,
) -> ToolReturn:
    """Run a shell command under a pseudo-terminal (for REPLs, TUIs).

    Args:
        command: Shell command to run under a PTY.
        cwd: Working directory relative to workspace root.
        env: Extra environment variables. Dangerous keys are blocked.
        timeout: Seconds before kill (foreground only).
        background: Return immediately with a session id for monitoring.
    """
    return await _run_exec(ctx, command, cwd, env, timeout, background, pty=True)
