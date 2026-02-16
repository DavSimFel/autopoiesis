"""Tests for subscription registry, processor, and tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart

from memory_store import init_memory_store, save_memory
from subscription_processor import (
    is_materialization,
    materialize_subscriptions,
    resolve_subscriptions,
)
from subscriptions import (
    MAX_CONTENT_CHARS,
    MAX_SUBSCRIPTIONS,
    SubscriptionRegistry,
)


@pytest.fixture()
def tmp_db(tmp_path: Path) -> str:
    return str(tmp_path / "subs.sqlite")


@pytest.fixture()
def registry(tmp_db: str) -> SubscriptionRegistry:
    return SubscriptionRegistry(tmp_db)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def memory_db(tmp_path: Path) -> str:
    db = str(tmp_path / "memory.sqlite")
    init_memory_store(db)
    return db


class TestSubscriptionRegistry:
    def test_add_and_get(self, registry: SubscriptionRegistry) -> None:
        sub = registry.add(kind="file", target="README.md")
        active = registry.get_active()
        assert len(active) == 1
        assert active[0].id == sub.id
        assert active[0].target == "README.md"

    def test_add_with_line_range(self, registry: SubscriptionRegistry) -> None:
        registry.add(kind="lines", target="f.py", line_range=(1, 10))
        active = registry.get_active()
        assert active[0].line_range == (1, 10)
        assert active[0].kind == "lines"

    def test_add_memory(self, registry: SubscriptionRegistry) -> None:
        sub = registry.add(kind="memory", target="auth decisions")
        assert sub.kind == "memory"

    def test_remove(self, registry: SubscriptionRegistry) -> None:
        sub = registry.add(kind="file", target="a.txt")
        assert registry.remove(sub.id)
        assert registry.get_active() == []

    def test_remove_nonexistent(self, registry: SubscriptionRegistry) -> None:
        assert not registry.remove("nonexistent")

    def test_remove_all(self, registry: SubscriptionRegistry) -> None:
        registry.add(kind="file", target="a.txt")
        registry.add(kind="file", target="b.txt")
        expected_removed = 2
        assert registry.remove_all() == expected_removed
        assert registry.get_active() == []

    def test_limit(self, registry: SubscriptionRegistry) -> None:
        for i in range(MAX_SUBSCRIPTIONS):
            registry.add(kind="file", target=f"file{i}.txt")
        with pytest.raises(ValueError, match="limit"):
            registry.add(kind="file", target="overflow.txt")

    def test_update_hash(self, registry: SubscriptionRegistry) -> None:
        sub = registry.add(kind="file", target="a.txt")
        registry.update_hash(sub.id, "abc123")
        active = registry.get_active()
        assert active[0].content_hash == "abc123"

    def test_upsert_same_target(self, tmp_db: str) -> None:
        reg = SubscriptionRegistry(tmp_db, session_id="s1")
        reg.add(kind="file", target="a.txt")
        reg.add(kind="file", target="a.txt")
        assert len(reg.get_active()) == 1


class TestResolveSubscriptions:
    def test_file_subscription(
        self,
        registry: SubscriptionRegistry,
        workspace: Path,
        memory_db: str,
    ) -> None:
        (workspace / "test.txt").write_text("hello world")
        registry.add(kind="file", target="test.txt")
        results = resolve_subscriptions(registry, workspace, memory_db)
        assert len(results) == 1
        assert "hello world" in results[0].content

    def test_file_truncation(
        self,
        registry: SubscriptionRegistry,
        workspace: Path,
        memory_db: str,
    ) -> None:
        big = "x" * (MAX_CONTENT_CHARS + 500)
        (workspace / "big.txt").write_text(big)
        registry.add(kind="file", target="big.txt")
        results = resolve_subscriptions(registry, workspace, memory_db)
        assert len(results[0].content) < len(big)
        assert "truncated" in results[0].content

    def test_line_range(
        self,
        registry: SubscriptionRegistry,
        workspace: Path,
        memory_db: str,
    ) -> None:
        lines = "\n".join(f"line {i}" for i in range(1, 21))
        (workspace / "f.txt").write_text(lines)
        registry.add(kind="lines", target="f.txt", line_range=(5, 10))
        results = resolve_subscriptions(registry, workspace, memory_db)
        assert "line 5" in results[0].content
        assert "line 10" in results[0].content
        assert "line 11" not in results[0].content

    def test_memory_subscription(
        self,
        registry: SubscriptionRegistry,
        workspace: Path,
        memory_db: str,
    ) -> None:
        save_memory(memory_db, "decided to use JWT auth", ["auth"])
        registry.add(kind="memory", target="auth")
        results = resolve_subscriptions(registry, workspace, memory_db)
        assert len(results) == 1
        assert "JWT" in results[0].content

    def test_missing_file(
        self,
        registry: SubscriptionRegistry,
        workspace: Path,
        memory_db: str,
    ) -> None:
        registry.add(kind="file", target="nope.txt")
        results = resolve_subscriptions(registry, workspace, memory_db)
        assert "not found" in results[0].content


class TestMaterializeSubscriptions:
    def test_injects_before_last_message(
        self,
        registry: SubscriptionRegistry,
        workspace: Path,
        memory_db: str,
    ) -> None:
        (workspace / "ctx.md").write_text("context data")
        registry.add(kind="file", target="ctx.md")
        user_msg = ModelRequest(parts=[UserPromptPart(content="hello")])
        result = materialize_subscriptions(
            [user_msg],
            registry,
            workspace,
            memory_db,
        )
        expected_count = 2
        assert len(result) == expected_count
        # Materialization is first, user message last
        assert is_materialization(result[0])
        assert result[1] is user_msg

    def test_strips_old_materializations(
        self,
        registry: SubscriptionRegistry,
        workspace: Path,
        memory_db: str,
    ) -> None:
        (workspace / "f.txt").write_text("data")
        registry.add(kind="file", target="f.txt")
        old_mat = ModelRequest(
            parts=[UserPromptPart(content="old")],
            metadata={"materialized_subscriptions": ["old_id"]},
        )
        user_msg = ModelRequest(parts=[UserPromptPart(content="hi")])
        result = materialize_subscriptions(
            [old_mat, user_msg],
            registry,
            workspace,
            memory_db,
        )
        # Old materialization stripped, new one added
        mat_msgs = [m for m in result if is_materialization(m)]
        assert len(mat_msgs) == 1

    def test_no_subscriptions_passthrough(
        self,
        registry: SubscriptionRegistry,
        workspace: Path,
        memory_db: str,
    ) -> None:
        user_msg = ModelRequest(parts=[UserPromptPart(content="hi")])
        result = materialize_subscriptions(
            [user_msg],
            registry,
            workspace,
            memory_db,
        )
        assert result == [user_msg]
