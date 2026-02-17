"""Shared fixtures for integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopoiesis.store.knowledge import init_knowledge_index
from autopoiesis.store.subscriptions import SubscriptionRegistry
from autopoiesis.topics.topic_manager import TopicRegistry


@pytest.fixture()
def topics_dir(tmp_path: Path) -> Path:
    d = tmp_path / "topics"
    d.mkdir()
    return d


@pytest.fixture()
def topic_registry(topics_dir: Path) -> TopicRegistry:
    return TopicRegistry(topics_dir)


@pytest.fixture()
def knowledge_root(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    root.mkdir()
    for sub in ("identity", "memory", "journal"):
        (root / sub).mkdir()
    return root


@pytest.fixture()
def knowledge_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "knowledge.sqlite")
    init_knowledge_index(db_path)
    return db_path


@pytest.fixture()
def workspace_root(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def subscription_registry(tmp_path: Path) -> SubscriptionRegistry:
    db_path = str(tmp_path / "subscriptions.sqlite")
    return SubscriptionRegistry(db_path, session_id="test-session")
