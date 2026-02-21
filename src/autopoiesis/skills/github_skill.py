"""GitHub skill command helpers that execute through the sandbox manager."""

from __future__ import annotations

import subprocess  # nosec B404 — used for CompletedProcess type; execution routes through SandboxManager
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from autopoiesis.security.subprocess_sandbox import SubprocessSandboxManager


@dataclass(frozen=True)
class GitHubSkillRunner:
    """Execute GitHub-oriented shell commands through a sandbox boundary."""

    sandbox: SubprocessSandboxManager

    def run_git(
        self,
        args: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command via :class:`SubprocessSandboxManager`."""
        return self.sandbox.run(["git", *args], cwd=cwd, env=env, timeout=timeout)


def run_github_git(
    sandbox: SubprocessSandboxManager,
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Convenience function for one-shot sandboxed git command execution."""
    return GitHubSkillRunner(sandbox=sandbox).run_git(args, cwd=cwd, env=env, timeout=timeout)
