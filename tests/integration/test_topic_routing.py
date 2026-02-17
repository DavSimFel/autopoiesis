"""Section 3: Topic Routing (Multi-Agent Foundation).

Tests 3.1-3.4 define WorkItem dispatch based on topic ownership (blocked).
Tests 3.5-3.6 test query_topics filtering - these work today.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autopoiesis.topics.topic_manager import (
    TopicRegistry,
    create_topic,
    query_topics,
)


def write_topic(topics_dir: Path, name: str, content: str) -> Path:
    p = topics_dir / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return p


_SKIP_ROUTING = pytest.mark.skip(
    reason="Blocked on #146 Phase A - WorkItem dispatch not implemented"
)

_DAILY_BRIEFING = (
    "---\ntype: task\nowner: planner\n"
    "triggers:\n  - type: cron\n    schedule: '0 9 * * *'\n"
    "---\nDaily briefing."
)

_PR_REVIEW = (
    "---\ntype: review\nowner: reviewer\n"
    "triggers:\n  - type: webhook\n    event: pr_opened\n"
    "---\nReview PRs."
)

_GENERAL_TASK = (
    "---\ntype: task\ntriggers:\n  - type: cron\n    schedule: '0 12 * * *'\n---\nGeneral work."
)


@_SKIP_ROUTING
class TestWorkItemTopicAutoActivation:
    """3.1 - WorkItem with topic_ref auto-activates topic."""

    def test_workitem_with_topic_ref_activates_topic(self, topics_dir: Path) -> None:
        write_topic(
            topics_dir,
            "fix-serve",
            "---\ntype: task\nstatus: open\n---\nFix serve bug.",
        )
        raise NotImplementedError("WorkItem dispatch not yet implemented")


@_SKIP_ROUTING
class TestOwnerBasedRouting:
    """3.2-3.4 - Topics with owner route to the correct agent."""

    def test_cron_trigger_routes_to_owner(self, topics_dir: Path) -> None:
        """3.2 - Cron trigger creates WorkItem targeting topic owner."""
        write_topic(topics_dir, "daily-briefing", _DAILY_BRIEFING)
        raise NotImplementedError("Owner-based routing not yet implemented")

    def test_webhook_trigger_routes_to_owner(self, topics_dir: Path) -> None:
        """3.3 - Webhook event creates WorkItem targeting topic owner."""
        write_topic(topics_dir, "pr-review", _PR_REVIEW)
        raise NotImplementedError("Owner-based routing not yet implemented")

    def test_no_owner_routes_to_default(self, topics_dir: Path) -> None:
        """3.4 - No owner routes to default/planner agent."""
        write_topic(topics_dir, "general-task", _GENERAL_TASK)
        raise NotImplementedError("Default routing not yet implemented")


class TestQueryTopicsFiltering:
    """3.5-3.6 - query_topics filters by owner and status.

    These helpers ARE implemented - tested here because they're the
    foundation for routing decisions.
    """

    def test_query_by_owner(self, topics_dir: Path) -> None:
        """3.5 - query_topics filters by owner."""
        registry = TopicRegistry(topics_dir)
        create_topic(registry, "coder-1", type="task", owner="coder", body="Task 1.")
        create_topic(
            registry,
            "reviewer-1",
            type="task",
            owner="reviewer",
            body="Task 2.",
        )
        create_topic(registry, "coder-2", type="task", owner="coder", body="Task 3.")

        results = query_topics(registry, owner="coder")
        assert len(results) == 2
        assert all(t.owner == "coder" for t in results)

    def test_query_by_status(self, topics_dir: Path) -> None:
        """3.6 - query_topics filters by status."""
        write_topic(
            topics_dir,
            "open-1",
            "---\ntype: task\nstatus: open\n---\nOpen 1.",
        )
        write_topic(
            topics_dir,
            "open-2",
            "---\ntype: task\nstatus: open\n---\nOpen 2.",
        )
        write_topic(
            topics_dir,
            "wip-1",
            "---\ntype: task\nstatus: in-progress\n---\nWIP.",
        )
        write_topic(
            topics_dir,
            "done-1",
            "---\ntype: task\nstatus: done\n---\nDone.",
        )
        registry = TopicRegistry(topics_dir)

        results = query_topics(registry, status="open")
        assert len(results) == 2
        assert all(t.status == "open" for t in results)
