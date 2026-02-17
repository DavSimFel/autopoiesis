"""Unit tests for tier-based approval enforcement in exec_tool."""

from __future__ import annotations

from autopoiesis.models import AgentDeps
from autopoiesis.tools.exec_tool import enforce_tier


def test_free_command_allowed_without_approval() -> None:
    """FREE commands pass tier check without approval unlock."""
    result = enforce_tier("echo hello", approval_unlocked=False)
    assert result is None


def test_review_command_blocked_without_approval() -> None:
    """REVIEW commands are blocked without approval unlock."""
    result = enforce_tier("git commit -m test", approval_unlocked=False)
    assert result is not None
    assert "review" in result.return_value.lower()  # type: ignore[union-attr]
    assert result.metadata is not None
    assert result.metadata.get("blocked") is True


def test_approve_command_blocked_without_approval() -> None:
    """APPROVE commands are blocked without approval unlock."""
    result = enforce_tier("rm -rf /tmp/nope", approval_unlocked=False)
    assert result is not None
    assert "approve" in result.return_value.lower()  # type: ignore[union-attr]
    assert result.metadata is not None
    assert result.metadata.get("blocked") is True


def test_block_tier_always_denied() -> None:
    """BLOCK-tier commands are denied even with approval unlocked."""
    for unlocked in (True, False):
        result = enforce_tier("sudo ls", approval_unlocked=unlocked)
        assert result is not None
        assert "block" in result.return_value.lower()  # type: ignore[union-attr]


def test_review_command_allowed_with_approval() -> None:
    """REVIEW commands pass when approval is unlocked."""
    result = enforce_tier("pip --version", approval_unlocked=True)
    assert result is None


def test_approve_command_allowed_with_approval() -> None:
    """APPROVE commands pass when approval is unlocked."""
    result = enforce_tier("curl --version", approval_unlocked=True)
    assert result is None


def test_batch_mode_approval_unlocked_defaults_false() -> None:
    """AgentDeps defaults approval_unlocked to False (batch mode behavior)."""
    backend = type("FakeBackend", (), {"root_dir": "/tmp/test"})()
    deps = AgentDeps(backend=backend)  # type: ignore[arg-type]
    assert deps.approval_unlocked is False
