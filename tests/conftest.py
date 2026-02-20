"""Shared test fixtures for autopoiesis."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai_backends import LocalBackend

from autopoiesis.infra.approval.keys import ApprovalKeyManager, KeyPaths
from autopoiesis.infra.approval.store import ApprovalStore
from autopoiesis.models import AgentDeps
from autopoiesis.store.history import init_history_store


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so pytest doesn't warn about unknown marks."""
    config.addinivalue_line(
        "markers",
        "verifies(*criterion_ids): marks a test as verifying one or more RTM criterion IDs. "
        "IDs must match entries in specs/modules/*.md Verification Criteria tables. "
        "Enforced by scripts/rtm_check.py in CI.",
    )


_TEST_PASSPHRASE = "test-passphrase-long-enough"
_TTL_SECONDS = 3600
_RETENTION_SECONDS = 7 * 24 * 3600
_CLOCK_SKEW_SECONDS = 60


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Temporary workspace directory for tests."""
    return tmp_path


@pytest.fixture()
def mock_deps(workspace: Path) -> AgentDeps:
    """AgentDeps with a LocalBackend pointing to the workspace."""
    return AgentDeps(backend=LocalBackend(root_dir=str(workspace), enable_execute=False))


@pytest.fixture()
def key_manager(tmp_path: Path) -> ApprovalKeyManager:
    """Unlocked ApprovalKeyManager with a test passphrase."""
    key_dir = tmp_path / "keys"
    paths = KeyPaths(
        key_dir=key_dir,
        private_key_path=key_dir / "approval.key",
        public_key_path=key_dir / "approval.pub",
        keyring_path=key_dir / "keyring.json",
    )
    manager = ApprovalKeyManager(paths)
    manager.create_initial_key(_TEST_PASSPHRASE)
    manager.unlock(_TEST_PASSPHRASE)
    return manager


@pytest.fixture()
def approval_store(tmp_path: Path) -> ApprovalStore:
    """ApprovalStore backed by a temporary SQLite database."""
    return ApprovalStore(
        db_path=tmp_path / "approvals.sqlite",
        ttl_seconds=_TTL_SECONDS,
        nonce_retention_seconds=_RETENTION_SECONDS,
        clock_skew_seconds=_CLOCK_SKEW_SECONDS,
    )


@pytest.fixture()
def history_db(tmp_path: Path) -> str:
    """Initialized temporary history SQLite database path."""
    db_path = str(tmp_path / "history.sqlite")
    init_history_store(db_path)
    return db_path
