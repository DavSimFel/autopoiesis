"""Section 2: Topic Lifecycle integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopoiesis.topics.topic_manager import (
    MAX_ACTIVE_TOPICS,
    TopicRegistry,
    build_topic_context,
    parse_topic,
    update_topic_status,
)


def write_topic(topics_dir: Path, name: str, content: str) -> Path:
    p = topics_dir / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return p


class TestTopicActivatesAndInjectsContext:
    """2.1 — Topic activates and injects context."""

    def test_active_topic_instructions_in_context(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "review", "---\npriority: normal\n---\nReview all PRs carefully.")
        registry = TopicRegistry(topics_dir)
        assert registry.activate("review")
        ctx = build_topic_context(registry)
        assert ctx is not None
        assert "Review all PRs carefully" in ctx.instructions


class TestTopicDeactivationRemovesContext:
    """2.2 — Topic deactivation removes context."""

    def test_deactivated_topic_gone_from_context(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "review", "---\npriority: normal\n---\nReview instructions.")
        registry = TopicRegistry(topics_dir)
        registry.activate("review")
        registry.deactivate("review")
        ctx = build_topic_context(registry)
        assert ctx is None


class TestMaxTopicsEnforced:
    """2.3 — Max 5 topics enforced."""

    def test_sixth_topic_raises(self, topics_dir: Path) -> None:
        for i in range(MAX_ACTIVE_TOPICS + 1):
            write_topic(topics_dir, f"topic-{i}", f"---\npriority: normal\n---\nTopic {i}.")
        registry = TopicRegistry(topics_dir)
        for i in range(MAX_ACTIVE_TOPICS):
            registry.activate(f"topic-{i}")
        with pytest.raises(ValueError, match="max concurrent topics"):
            registry.activate(f"topic-{MAX_ACTIVE_TOPICS}")


class TestTopicPriorityOrdering:
    """2.4 — Topic priority ordering."""

    def test_critical_before_normal_before_low(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "low-task", "---\npriority: low\n---\nLow work.")
        write_topic(
            topics_dir,
            "critical-task",
            "---\npriority: critical\n---\nCritical work.",
        )
        write_topic(
            topics_dir,
            "normal-task",
            "---\npriority: normal\n---\nNormal work.",
        )
        registry = TopicRegistry(topics_dir)
        registry.activate("low-task")
        registry.activate("critical-task")
        registry.activate("normal-task")
        ctx = build_topic_context(registry)
        assert ctx is not None
        ins = ctx.instructions
        assert ins.index("critical-task") < ins.index("normal-task")
        assert ins.index("normal-task") < ins.index("low-task")


class TestTopicStatusUpdatePersists:
    """2.5 — Topic status update persists."""

    def test_status_written_to_disk(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "fix-bug", "---\ntype: task\nstatus: open\n---\nFix the bug.")
        registry = TopicRegistry(topics_dir)
        result = update_topic_status(registry, "fix-bug", "in-progress")
        assert "updated" in result
        updated = parse_topic(topics_dir / "fix-bug.md")
        assert updated.status == "in-progress"
        assert "Fix the bug" in updated.instructions

    def test_body_preserved_after_update(self, topics_dir: Path) -> None:
        body = "Special chars: é, ñ, ü, ₿."
        write_topic(topics_dir, "task-a", f"---\ntype: task\nstatus: open\n---\n{body}")
        registry = TopicRegistry(topics_dir)
        update_topic_status(registry, "task-a", "in-progress")
        updated = parse_topic(topics_dir / "task-a.md")
        assert body in updated.instructions


class TestInvalidStatusTransitionRejected:
    """2.6 — Invalid status transition rejected."""

    def test_done_to_open_rejected(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "fix-bug", "---\ntype: task\nstatus: done\n---\nDone bug.")
        registry = TopicRegistry(topics_dir)
        result = update_topic_status(registry, "fix-bug", "open")
        assert "Cannot transition" in result

    def test_general_has_no_lifecycle(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "chat", "---\ntype: general\n---\nGeneral topic.")
        registry = TopicRegistry(topics_dir)
        result = update_topic_status(registry, "chat", "in-progress")
        assert "general" in result.lower()

    def test_full_valid_task_lifecycle(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "lifecycle", "---\ntype: task\nstatus: open\n---\nLifecycle test.")
        registry = TopicRegistry(topics_dir)
        for status in ["in-progress", "review", "done", "archived"]:
            result = update_topic_status(registry, "lifecycle", status)
            assert "updated" in result
        assert parse_topic(topics_dir / "lifecycle.md").status == "archived"
