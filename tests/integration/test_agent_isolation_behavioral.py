"""Behavioral agent isolation tests with real stores and runtime wiring."""

from __future__ import annotations

import os
from pathlib import Path

from autopoiesis.agent.workspace import resolve_agent_workspace
from autopoiesis.store.history import init_history_store, load_checkpoint, save_checkpoint
from autopoiesis.store.knowledge import (
    index_file,
    init_knowledge_index,
    search_knowledge,
)
from autopoiesis.store.subscriptions import SubscriptionRegistry
from autopoiesis.topics.topic_manager import TopicRegistry, create_topic


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


class TestKnowledgeStoreIsolation:
    """Two agents with separate knowledge DBs cannot see each other's indexed content."""

    def test_knowledge_search_isolated_with_real_db(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            # Set up knowledge for alpha
            alpha.knowledge.mkdir(parents=True, exist_ok=True)
            alpha_db = str(alpha.root / "knowledge.sqlite")
            init_knowledge_index(alpha_db)
            doc = alpha.knowledge / "secret.md"
            doc.write_text("Alpha's secret algorithm for quantum computing.")
            index_file(alpha_db, alpha.knowledge, doc)

            # Set up knowledge for beta
            beta.knowledge.mkdir(parents=True, exist_ok=True)
            beta_db = str(beta.root / "knowledge.sqlite")
            init_knowledge_index(beta_db)
            beta_doc = beta.knowledge / "notes.md"
            beta_doc.write_text("Beta's notes on machine learning.")
            index_file(beta_db, beta.knowledge, beta_doc)

            # Alpha can find its content
            alpha_results = search_knowledge(alpha_db, "quantum")
            assert len(alpha_results) > 0

            # Beta cannot find alpha's content
            beta_results = search_knowledge(beta_db, "quantum")
            assert len(beta_results) == 0

            # Beta can find its own content
            beta_own = search_knowledge(beta_db, "machine learning")
            assert len(beta_own) > 0


class TestSubscriptionStoreIsolation:
    """Two agents with separate subscription DBs have independent subscriptions."""

    def test_subscriptions_isolated(self, tmp_path: Path) -> None:
        alpha_db = str(tmp_path / "alpha_subs.sqlite")
        beta_db = str(tmp_path / "beta_subs.sqlite")

        alpha_reg = SubscriptionRegistry(alpha_db, session_id="alpha-session")
        beta_reg = SubscriptionRegistry(beta_db, session_id="beta-session")

        alpha_reg.add("file", "alpha-secret.py")
        beta_reg.add("file", "beta-public.py")

        assert len(alpha_reg.get_active()) == 1
        assert alpha_reg.get_active()[0].target == "alpha-secret.py"

        assert len(beta_reg.get_active()) == 1
        assert beta_reg.get_active()[0].target == "beta-public.py"


class TestCheckpointIsolation:
    """Checkpoints are isolated per history DB."""

    def test_checkpoints_isolated(self, tmp_path: Path) -> None:
        alpha_db = str(tmp_path / "alpha_history.sqlite")
        beta_db = str(tmp_path / "beta_history.sqlite")

        init_history_store(alpha_db)
        init_history_store(beta_db)

        save_checkpoint(alpha_db, "item-1", '["alpha msg"]', round_count=1)
        save_checkpoint(beta_db, "item-1", '["beta msg"]', round_count=1)

        # Same item ID, different DBs → different content
        assert load_checkpoint(alpha_db, "item-1") == '["alpha msg"]'
        assert load_checkpoint(beta_db, "item-1") == '["beta msg"]'


class TestTopicIsolationBehavioral:
    """Topics created by one agent are invisible to another agent's registry."""

    def test_topic_creation_isolated(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            alpha_topics = alpha.knowledge / "topics"
            beta_topics = beta.knowledge / "topics"
            alpha_topics.mkdir(parents=True, exist_ok=True)
            beta_topics.mkdir(parents=True, exist_ok=True)

            alpha_reg = TopicRegistry(alpha_topics)
            beta_reg = TopicRegistry(beta_topics)

            create_topic(alpha_reg, "alpha-task", type="task", body="Alpha's task.")

            # Beta's registry should not see alpha's topic
            assert beta_reg.get_topic("alpha-task") is None
            assert len(beta_reg.list_topics()) == 0

            # Alpha's registry should see it
            assert alpha_reg.get_topic("alpha-task") is not None
            assert len(alpha_reg.list_topics()) == 1
