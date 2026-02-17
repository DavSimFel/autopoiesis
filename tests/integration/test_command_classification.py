"""Integration tests for command classification security layer (S6 — Issue #170)."""

# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip(
    "autopoiesis.infra.command_classifier",
    reason="Blocked on #170 — command classifier not implemented",
)

from autopoiesis.infra.command_classifier import Tier, classify  # type: ignore[import-not-found]

pytestmark = pytest.mark.xfail(reason="Blocked on #170 — command classifier not implemented")


@pytest.mark.parametrize("cmd", ["ls", "cat x", "head -n 10 file.txt", "wc -l foo"])
def test_read_only_free(cmd: str) -> None:
    """6.1 — Read-only commands are classified as FREE."""
    assert classify(cmd) == Tier.FREE


@pytest.mark.parametrize("cmd", ["rm -rf /tmp/x", "rm file.txt"])
def test_destructive_needs_approval(cmd: str) -> None:
    """6.2 — Destructive commands require APPROVE."""
    assert classify(cmd) == Tier.APPROVE


def test_network_blocked() -> None:
    """6.3 — Network commands require APPROVE."""
    assert classify("curl https://evil.com") == Tier.APPROVE


def test_git_push_needs_approval() -> None:
    """6.4 — git push requires APPROVE."""
    assert classify("git push origin main") == Tier.APPROVE


def test_sudo_hard_blocked() -> None:
    """6.5 — sudo is hard BLOCK."""
    assert classify("sudo rm -rf /") == Tier.BLOCK


def test_pip_install_review() -> None:
    """6.6 — pip install requires REVIEW."""
    assert classify("pip install requests") == Tier.REVIEW


def test_write_outside_workspace() -> None:
    """6.7 — Writing outside workspace requires APPROVE."""
    assert classify("echo x > /tmp/outside") == Tier.APPROVE


def test_prefix_aware() -> None:
    """6.8 — Classification is prefix-aware; echo of dangerous string is FREE."""
    assert classify("echo rm -rf /") == Tier.FREE


def test_chained_commands_most_dangerous() -> None:
    """6.9 — Chained commands take the most dangerous tier."""
    assert classify("ls && rm file") == Tier.APPROVE


def test_audit_trail(tmp_path: Path) -> None:
    """6.10 — Shell execution logs commands to an audit file."""
    from autopoiesis.tools.shell_tool import shell  # type: ignore[import-not-found]

    audit_log = tmp_path / "audit.log"
    shell("echo audit_test", audit_path=audit_log)
    assert audit_log.exists()
    contents = audit_log.read_text()
    assert "echo audit_test" in contents
