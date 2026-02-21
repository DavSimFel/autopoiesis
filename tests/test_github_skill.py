"""Tests for GitHub skill subprocess routing through sandbox manager."""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock

from autopoiesis.security.subprocess_sandbox import SubprocessSandboxManager
from autopoiesis.skills.github_skill import GitHubSkillRunner, run_github_git


def test_github_skill_runner_delegates_to_sandbox() -> None:
    sandbox = MagicMock(spec=SubprocessSandboxManager)
    expected = CompletedProcess(args=["git", "status"], returncode=0, stdout="ok", stderr="")
    sandbox.run.return_value = expected
    runner = GitHubSkillRunner(sandbox=sandbox)

    result = runner.run_git(["status"], cwd="repo")

    assert result is expected
    sandbox.run.assert_called_once_with(["git", "status"], cwd="repo", env=None, timeout=None)


def test_run_github_git_helper_uses_runner_contract(tmp_path: Path) -> None:
    sandbox = MagicMock(spec=SubprocessSandboxManager)
    expected = CompletedProcess(args=["git", "log"], returncode=0, stdout="", stderr="")
    sandbox.run.return_value = expected

    result = run_github_git(
        sandbox,
        ["log", "--oneline"],
        cwd=tmp_path / "repo",
        env={"GIT_TRACE": "0"},
        timeout=5.0,
    )

    assert result is expected
    sandbox.run.assert_called_once_with(
        ["git", "log", "--oneline"],
        cwd=Path(tmp_path / "repo"),
        env={"GIT_TRACE": "0"},
        timeout=5.0,
    )
