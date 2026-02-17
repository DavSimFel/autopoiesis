"""Unified shell tool replacing exec_tool + process_tool (Issue #170)."""

from __future__ import annotations

import os
import subprocess  # nosec B404 — shell execution is this module's purpose
from dataclasses import dataclass
from pathlib import Path

_MAX_OUTPUT_BYTES = 10 * 1024  # 10 KB

_ENV_WHITELIST: frozenset[str] = frozenset({"PATH", "HOME", "USER", "LANG", "TERM"})

# Paths that should not be readable by shell commands
_BLOCKED_PATHS: tuple[str, ...] = ("/etc/shadow", "/etc/gshadow")


@dataclass
class ShellResult:
    """Result of a shell command execution."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    truncated: bool = False
    blocked: bool = False


def _resolve_workspace() -> Path:
    raw = os.getenv("AGENT_WORKSPACE_ROOT", "")
    if raw:
        p = Path(raw)
        if p.is_absolute():
            return p
    # Fallback: repo root / data/agent-workspace
    return Path(__file__).resolve().parents[3] / "data" / "agent-workspace"


def _safe_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in _ENV_WHITELIST}


def _truncate(text: str) -> tuple[str, bool]:
    if len(text.encode("utf-8", errors="replace")) <= _MAX_OUTPUT_BYTES:
        return text, False
    half = _MAX_OUTPUT_BYTES // 2
    # Work with bytes for accurate size
    encoded = text.encode("utf-8", errors="replace")
    first = encoded[:half].decode("utf-8", errors="replace")
    last = encoded[-half:].decode("utf-8", errors="replace")
    return first + "\n[... truncated ...]\n" + last, True


def _is_blocked(command: str) -> bool:
    """Check if command tries to access blocked paths."""
    return any(p in command for p in _BLOCKED_PATHS)


def shell(
    command: str,
    timeout: int = 30,
    audit_path: Path | None = None,
) -> ShellResult:
    """Execute a shell command in a sandboxed environment."""
    if _is_blocked(command):
        result = ShellResult(
            stderr="Access denied: blocked path",
            exit_code=1,
            blocked=True,
        )
        if audit_path is not None:
            from autopoiesis.infra.audit_log import log_command

            log_command(command, result, audit_path)
        return result

    workspace = _resolve_workspace()
    workspace.mkdir(parents=True, exist_ok=True)
    env = _safe_env()

    timed_out = False
    try:
        proc = subprocess.run(  # nosec B602 — shell=True is intentional; commands are classified by command_classifier
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace),
            env=env,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        stdout = ""
        stderr = "Command timed out"
        exit_code = -1
        timed_out = True

    stdout, truncated = _truncate(stdout)

    result = ShellResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        timed_out=timed_out,
        truncated=truncated,
    )

    if audit_path is not None:
        from autopoiesis.infra.audit_log import log_command

        log_command(command, result, audit_path)

    return result
