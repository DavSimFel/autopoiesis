"""Integration tests for the unified shell tool (S5 — Issue #170)."""

# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false

from __future__ import annotations

import pytest
from autopoiesis.tools.shell_tool import shell  # type: ignore[import-not-found]

pytestmark = pytest.mark.xfail(reason="Blocked on #170 — shell tool not implemented")


def test_simple_command(workspace_root: object) -> None:
    """5.1 — shell("echo hello") returns stdout containing 'hello'."""
    result = shell("echo hello")
    assert "hello" in result.stdout


def test_exit_code_propagated() -> None:
    """5.2 — Non-zero exit codes are propagated."""
    result = shell("exit 1")
    assert result.exit_code == 1


def test_stderr_captured() -> None:
    """5.3 — Stderr is captured separately."""
    result = shell("ls /nonexistent_path_xyz")
    assert result.stderr
    assert result.exit_code != 0


def test_timeout_enforced() -> None:
    """5.4 — Long-running commands are killed after timeout."""
    result = shell("sleep 999", timeout=1)
    assert result.timed_out is True


def test_output_truncation() -> None:
    """5.5 — Huge stdout is truncated, preserving first and last lines."""
    result = shell("seq 1 100000")
    assert result.truncated is True
    assert "1" in result.stdout
    assert "100000" in result.stdout


def test_cwd_sandboxed(tmp_path: object) -> None:
    """5.6 — Working directory is within the agent workspace."""
    result = shell("pwd")
    # The exact workspace path is implementation-defined; just confirm it's not /.
    assert result.stdout.strip() != "/"


def test_cwd_escape_blocked() -> None:
    """5.7 — Reading sensitive host files is blocked."""
    result = shell("cat /etc/shadow")
    assert result.exit_code != 0 or result.blocked is True


def test_background_via_tmux() -> None:
    """5.8 — Background commands via tmux are supported."""
    result = shell("tmux new -d -s bg_test 'sleep 10'")
    assert result.exit_code == 0


def test_pipe_composition() -> None:
    """5.9 — Pipe composition works correctly."""
    result = shell("echo -e 'a\nb\nc' | wc -l")
    assert result.stdout.strip() == "3"


def test_environment_isolation() -> None:
    """5.10 — Host secrets are not leaked to child processes."""
    result = shell("env")
    for secret_key in ("AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        assert secret_key not in result.stdout
