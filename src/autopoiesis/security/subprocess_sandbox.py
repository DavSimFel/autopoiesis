"""Sandbox manager for subprocess execution with path and resource controls."""

from __future__ import annotations

import resource
import subprocess  # nosec B404 — intentional: sandbox controls all subprocess calls
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from autopoiesis.security.path_validator import PathValidator

_DEFAULT_MAX_PROCESSES = 64
_DEFAULT_MAX_FILE_SIZE_BYTES = 16 * 1024 * 1024
_DEFAULT_MAX_CPU_SECONDS = 30


@dataclass(frozen=True)
class SandboxLimits:
    """Resource caps applied to sandboxed child processes."""

    max_processes: int = _DEFAULT_MAX_PROCESSES
    max_file_size_bytes: int = _DEFAULT_MAX_FILE_SIZE_BYTES
    max_cpu_seconds: int = _DEFAULT_MAX_CPU_SECONDS

    def __post_init__(self) -> None:
        if self.max_processes <= 0:
            raise ValueError("max_processes must be > 0.")
        if self.max_file_size_bytes <= 0:
            raise ValueError("max_file_size_bytes must be > 0.")
        if self.max_cpu_seconds <= 0:
            raise ValueError("max_cpu_seconds must be > 0.")


def _bounded_soft_limit(target: int, hard: int) -> int:
    if hard == resource.RLIM_INFINITY:
        return target
    return min(target, hard)


def _set_limit(limit_name: str, target: int) -> None:
    limit = getattr(resource, limit_name, None)
    if limit is None:
        return
    _, hard = resource.getrlimit(limit)
    resource.setrlimit(limit, (_bounded_soft_limit(target, hard), hard))


class SubprocessSandboxManager:
    """Apply filesystem isolation and process limits to subprocess execution."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        allowed_roots: Sequence[Path] | None = None,
        limits: SandboxLimits | None = None,
    ) -> None:
        allowlist = tuple(allowed_roots) if allowed_roots is not None else ()
        self._path_validator = PathValidator(workspace_root=workspace_root, allowed_roots=allowlist)
        self._limits = limits or SandboxLimits()

    @property
    def path_validator(self) -> PathValidator:
        """Return the active path validator used by the sandbox."""
        return self._path_validator

    def resolve_cwd(self, cwd: str | Path | None = None) -> Path:
        """Resolve the subprocess working directory inside the allowlist."""
        if cwd is None:
            return self._path_validator.workspace_root
        return self._path_validator.resolve_path(cwd)

    def preexec_fn(self) -> Callable[[], None]:
        """Return a pre-exec hook that applies RLIMIT-based restrictions."""
        limits = self._limits

        def _apply_limits() -> None:
            _set_limit("RLIMIT_NPROC", limits.max_processes)
            _set_limit("RLIMIT_FSIZE", limits.max_file_size_bytes)
            _set_limit("RLIMIT_CPU", limits.max_cpu_seconds)

        return _apply_limits

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Execute *command* with sandbox path validation and limits."""
        safe_cwd = str(self.resolve_cwd(cwd))
        safe_command = [str(part) for part in command]
        return subprocess.run(  # nosec B603 — command is a validated list, shell=False (default)
            safe_command,
            cwd=safe_cwd,
            env=dict(env) if env is not None else None,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
            preexec_fn=self.preexec_fn(),
        )
