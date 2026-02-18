"""Unit tests for tier-based approval enforcement in exec_tool."""

from __future__ import annotations

from typing import cast

from pydantic_ai_backends import LocalBackend

from autopoiesis.models import AgentDeps
from autopoiesis.tools.tier_enforcement import enforce_tier


def test_free_command_allowed_without_approval() -> None:
    """FREE commands pass tier check without approval unlock."""
    result = enforce_tier("echo hello", approval_unlocked=False)
    assert result is None


def test_review_command_blocked_without_approval() -> None:
    """REVIEW commands are blocked without approval unlock."""
    result = enforce_tier("git commit -m test", approval_unlocked=False)
    assert result is not None
    return_value = result.return_value
    assert isinstance(return_value, str)
    assert "review" in return_value.lower()
    assert result.metadata is not None
    assert result.metadata.get("blocked") is True


def test_approve_command_blocked_without_approval() -> None:
    """APPROVE commands are blocked without approval unlock."""
    result = enforce_tier("rm -rf /tmp/nope", approval_unlocked=False)
    assert result is not None
    return_value = result.return_value
    assert isinstance(return_value, str)
    assert "approve" in return_value.lower()
    assert result.metadata is not None
    assert result.metadata.get("blocked") is True


def test_block_tier_always_denied() -> None:
    """BLOCK-tier commands are denied even with approval unlocked."""
    for unlocked in (True, False):
        result = enforce_tier("sudo ls", approval_unlocked=unlocked)
        assert result is not None
        return_value = result.return_value
        assert isinstance(return_value, str)
        assert "block" in return_value.lower()


def test_review_command_allowed_with_approval() -> None:
    """REVIEW commands pass when approval is unlocked."""
    result = enforce_tier("pip --version", approval_unlocked=True)
    assert result is None


def test_approve_command_allowed_with_approval() -> None:
    """APPROVE commands pass when approval is unlocked."""
    result = enforce_tier("curl --version", approval_unlocked=True)
    assert result is None


def test_python_command_blocked_without_approval() -> None:
    """Interpreter commands require REVIEW tier without approval unlock."""
    result = enforce_tier("python -c \"print('hi')\"", approval_unlocked=False)
    assert result is not None
    return_value = result.return_value
    assert isinstance(return_value, str)
    assert "review" in return_value.lower()


def test_tmux_command_blocked_without_approval() -> None:
    """Session-manager commands require REVIEW tier without approval unlock."""
    result = enforce_tier("tmux new -d -s session 'sleep 1'", approval_unlocked=False)
    assert result is not None
    return_value = result.return_value
    assert isinstance(return_value, str)
    assert "review" in return_value.lower()


def test_python_command_allowed_with_approval() -> None:
    """Interpreter commands pass tier checks when approval is unlocked."""
    result = enforce_tier("python -c \"print('hi')\"", approval_unlocked=True)
    assert result is None


def test_tmux_command_allowed_with_approval() -> None:
    """Session-manager commands pass tier checks when approval is unlocked."""
    result = enforce_tier("tmux new -d -s session 'sleep 1'", approval_unlocked=True)
    assert result is None


def test_batch_mode_approval_unlocked_defaults_false() -> None:
    """AgentDeps defaults approval_unlocked to False (batch mode behavior)."""
    backend = cast(LocalBackend, type("FakeBackend", (), {"root_dir": "/tmp/test"})())
    deps = AgentDeps(backend=backend)
    assert deps.approval_unlocked is False
