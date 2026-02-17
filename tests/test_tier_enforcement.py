"""Unit tests for tier-based approval enforcement in shell_tool."""

from __future__ import annotations

from autopoiesis.tools.shell_tool import shell


def test_free_command_without_approval() -> None:
    """FREE commands execute when approval is not unlocked."""
    result = shell("echo hello", approval_unlocked=False)
    assert not result.blocked
    assert "hello" in result.stdout


def test_review_command_blocked_without_approval() -> None:
    """REVIEW commands are blocked when approval is not unlocked."""
    result = shell("git commit --allow-empty -m test", approval_unlocked=False)
    assert result.blocked
    assert result.exit_code == 1
    assert "review" in result.stderr.lower()


def test_approve_command_blocked_without_approval() -> None:
    """APPROVE commands are blocked when approval is not unlocked."""
    result = shell("git push origin main", approval_unlocked=False)
    assert result.blocked
    assert result.exit_code == 1
    assert "approve" in result.stderr.lower()


def test_review_command_allowed_with_approval() -> None:
    """REVIEW commands execute when approval is unlocked."""
    result = shell("pip --version", approval_unlocked=True)
    assert not result.blocked


def test_approve_command_allowed_with_approval() -> None:
    """APPROVE commands execute when approval is unlocked."""
    # curl --version is classified as APPROVE tier but is safe to run
    result = shell("curl --version", approval_unlocked=True)
    assert not result.blocked


def test_block_tier_always_blocked() -> None:
    """BLOCK-tier commands are rejected regardless of approval state."""
    for unlocked in (True, False):
        result = shell("sudo ls", approval_unlocked=unlocked)
        assert result.blocked
        assert result.exit_code == 1
        assert "block" in result.stderr.lower()
