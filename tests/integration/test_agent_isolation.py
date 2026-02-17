"""Section 6: Agent Isolation (Multi-Agent) integration tests.

Tests verify that agents get isolated directory trees and cannot see
each other's knowledge, topics, or state.
"""

from __future__ import annotations

import os
from pathlib import Path

from autopoiesis.agent.workspace import resolve_agent_workspace
from autopoiesis.topics.topic_manager import TopicRegistry


class TestAgentPathIsolation:
    """6.1 — Two agents resolve different paths."""

    def test_different_agents_different_paths(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            assert alpha.root != beta.root
            assert alpha.workspace != beta.workspace
            assert alpha.knowledge != beta.knowledge
            assert alpha.skills != beta.skills

    def test_no_path_overlap(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            # No alpha path should be a parent/child of any beta path
            alpha_paths = {alpha.root, alpha.workspace, alpha.knowledge, alpha.skills}
            beta_paths = {beta.root, beta.workspace, beta.knowledge, beta.skills}
            for ap in alpha_paths:
                for bp in beta_paths:
                    assert not ap.is_relative_to(bp)
                    assert not bp.is_relative_to(ap)


class TestAgentKnowledgeIsolation:
    """6.2 — Agent A cannot see Agent B knowledge."""

    def test_knowledge_search_isolated(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            # Create knowledge dirs and files
            alpha.knowledge.mkdir(parents=True, exist_ok=True)
            beta.knowledge.mkdir(parents=True, exist_ok=True)

            (alpha.knowledge / "secret.md").write_text("alpha secret data")

            # Beta's knowledge dir should NOT contain alpha's file
            beta_files = list(beta.knowledge.glob("*.md"))
            assert len(beta_files) == 0

            # Alpha's knowledge should contain the file
            alpha_files = list(alpha.knowledge.glob("*.md"))
            assert len(alpha_files) == 1
            assert alpha_files[0].name == "secret.md"


class TestAgentTopicIsolation:
    """6.3 — Agent A cannot see Agent B topics."""

    def test_topic_listing_isolated(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            # Create topics dirs
            alpha_topics = alpha.knowledge / "topics"
            beta_topics = beta.knowledge / "topics"
            alpha_topics.mkdir(parents=True, exist_ok=True)
            beta_topics.mkdir(parents=True, exist_ok=True)

            # Agent A creates a topic
            (alpha_topics / "my-task.md").write_text("---\ntype: task\n---\nAlpha's private task")

            # Agent B lists topics → should NOT see alpha's topic
            beta_registry = TopicRegistry(beta_topics)
            assert beta_registry.get_topic("my-task") is None
            assert len(beta_registry.list_topics()) == 0

            # Agent A's registry SHOULD see it
            alpha_registry = TopicRegistry(alpha_topics)
            assert alpha_registry.get_topic("my-task") is not None


class TestSharedDBOS:
    """6.4 — Shared DBOS system DB.

    Two agents share the same system database but have different agent_ids
    on their WorkItems.
    """

    def test_agents_share_system_db(self, tmp_path: Path) -> None:
        """Verify dispatch_workitem routes different agent_ids to different queues."""
        from autopoiesis.infra.work_queue import dispatch_workitem
        from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

        item_a = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hello from alpha"),
            agent_id="alpha",
        )
        item_b = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hello from beta"),
            agent_id="beta",
        )

        queue_a = dispatch_workitem(item_a)
        queue_b = dispatch_workitem(item_b)

        # Different agent_ids → different queues
        assert queue_a is not queue_b
        assert queue_a.name == "agent_work_alpha"
        assert queue_b.name == "agent_work_beta"

        # Same agent_id → same queue
        item_a2 = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="another from alpha"),
            agent_id="alpha",
        )
        assert dispatch_workitem(item_a2) is queue_a
        assert item_a.id != item_b.id


class TestDefaultAgentBackwardCompatible:
    """6.5 — Default agent = backward compatible."""

    def test_no_agent_flag_resolves_to_default(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            paths = resolve_agent_workspace(None)
            assert paths.root.name == "default"
            assert "agents/default" in str(paths.root)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AutopoiesisHome:
    """Context manager to temporarily set AUTOPOIESIS_HOME."""

    def __init__(self, tmp_path: Path) -> None:
        self._home = str(tmp_path / ".autopoiesis")
        self._old: str | None = None

    def __enter__(self) -> str:
        self._old = os.environ.get("AUTOPOIESIS_HOME")
        os.environ["AUTOPOIESIS_HOME"] = self._home
        return self._home

    def __exit__(self, *args: object) -> None:
        if self._old is None:
            os.environ.pop("AUTOPOIESIS_HOME", None)
        else:
            os.environ["AUTOPOIESIS_HOME"] = self._old
