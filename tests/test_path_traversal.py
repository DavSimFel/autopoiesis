"""Tests for path traversal protection in subscription materialization."""

from __future__ import annotations

from pathlib import Path

import pytest

from infra.subscription_processor import resolve_subscriptions
from store.knowledge import init_knowledge_index
from store.subscriptions import SubscriptionRegistry


def _knowledge_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "knowledge.sqlite")
    init_knowledge_index(db_path)
    return db_path


def _registry(tmp_path: Path) -> SubscriptionRegistry:
    return SubscriptionRegistry(str(tmp_path / "subscriptions.sqlite"))


@pytest.mark.parametrize(
    "target",
    [
        "../../../etc/passwd",
        "..//..//..//etc/passwd",
        "/etc/passwd",
        "../workspace-escape/secret.txt",
    ],
)
def test_traversal_paths_are_rejected(tmp_path: Path, target: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = _registry(tmp_path)
    registry.add(kind="file", target=target)

    results = resolve_subscriptions(registry, workspace, _knowledge_db(tmp_path))

    assert len(results) == 1
    assert "escapes workspace root" in results[0].content


def test_valid_workspace_path_is_accepted(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    docs = workspace / "docs"
    docs.mkdir()
    target = docs / "notes.txt"
    target.write_text("line one\nline two")
    registry = _registry(tmp_path)
    registry.add(kind="file", target="docs/notes.txt")

    results = resolve_subscriptions(registry, workspace, _knowledge_db(tmp_path))

    assert len(results) == 1
    assert results[0].content == "line one\nline two"
