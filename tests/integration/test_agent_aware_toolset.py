"""Integration tests for agent-aware toolset initialisation (Issue #202).

Verifies that :func:`prepare_toolset_context` scopes every mutable store
(knowledge DB, subscriptions DB, topics directory, workspace root) under the
selected :class:`AgentPaths`, giving each agent identity an isolated filesystem
tree with no cross-contamination.

Acceptance criteria from #202:
- Toolset preparation accepts selected agent workspace/path inputs.
- Backend root, knowledge root, topics dir, subscriptions DB, and temp dirs
  resolve under selected agent paths.
- No shared mutable state between two agents except the explicitly shared
  system DBOS database.
- Integration tests prove isolation for knowledge/topics/subscriptions paths
  across two agent identities.
"""

from __future__ import annotations

import os
from pathlib import Path

from autopoiesis.agent.workspace import AgentPaths, resolve_agent_workspace
from autopoiesis.store.knowledge import index_file, search_knowledge
from autopoiesis.store.subscriptions import SubscriptionRegistry
from autopoiesis.topics.topic_manager import TopicRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AutopoiesisHome:
    """Context manager that temporarily redirects AUTOPOIESIS_HOME."""

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


def _run_prepare_toolset_context(agent_paths: AgentPaths) -> tuple[
    Path, str, SubscriptionRegistry, TopicRegistry, list, str
]:
    """Thin wrapper so callers don't have to import the builder directly."""
    from autopoiesis.tools.toolset_builder import prepare_toolset_context

    return prepare_toolset_context(agent_paths)


# ---------------------------------------------------------------------------
# Test: build_backend is agent-scoped
# ---------------------------------------------------------------------------


class TestBuildBackendAgentScoped:
    """build_backend() roots the LocalBackend at agent_paths.workspace."""

    def test_backend_root_matches_agent_workspace(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            paths = resolve_agent_workspace("builder-test")
            from autopoiesis.tools.toolset_builder import build_backend

            backend = build_backend(paths)
            assert Path(backend.root_dir).resolve() == paths.workspace.resolve()

    def test_backend_roots_differ_across_agents(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha_paths = resolve_agent_workspace("alpha")
            beta_paths = resolve_agent_workspace("beta")
            from autopoiesis.tools.toolset_builder import build_backend

            alpha_backend = build_backend(alpha_paths)
            beta_backend = build_backend(beta_paths)
            assert Path(alpha_backend.root_dir) != Path(beta_backend.root_dir)

    def test_workspace_directory_created(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            paths = resolve_agent_workspace("new-agent")
            assert not paths.workspace.exists()
            from autopoiesis.tools.toolset_builder import build_backend

            build_backend(paths)
            assert paths.workspace.is_dir()


# ---------------------------------------------------------------------------
# Test: prepare_toolset_context path isolation
# ---------------------------------------------------------------------------


class TestPrepareToolsetContextPaths:
    """All sub-store paths produced by prepare_toolset_context are agent-scoped."""

    def test_workspace_root_under_agent_paths(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            paths = resolve_agent_workspace("path-test")
            workspace_root, *_ = _run_prepare_toolset_context(paths)
            assert workspace_root == paths.workspace

    def test_knowledge_db_under_agent_data(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            paths = resolve_agent_workspace("kb-test")
            _, knowledge_db_path, *_ = _run_prepare_toolset_context(paths)
            assert Path(knowledge_db_path).parent.resolve() == paths.data.resolve()

    def test_subscription_db_under_agent_data(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            paths = resolve_agent_workspace("sub-test")
            _run_prepare_toolset_context(paths)
            # Verify the DB file was created under the agent's data directory
            sub_db = paths.data / "subscriptions.sqlite"
            assert sub_db.exists(), "subscriptions.sqlite should be created under agent data dir"

    def test_topics_dir_under_agent_knowledge(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            paths = resolve_agent_workspace("topic-test")
            _, _, _, topic_reg, *_ = _run_prepare_toolset_context(paths)
            assert topic_reg.topics_dir.resolve().is_relative_to(paths.knowledge.resolve())

    def test_two_agents_have_non_overlapping_paths(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            alpha_ws, alpha_kb, _alpha_sub, alpha_tr, *_ = _run_prepare_toolset_context(alpha)
            beta_ws, beta_kb, _beta_sub, beta_tr, *_ = _run_prepare_toolset_context(beta)

            assert alpha_ws != beta_ws
            assert alpha_kb != beta_kb
            assert alpha_tr.topics_dir != beta_tr.topics_dir
            # Subscription DBs must also be disjoint
            assert (alpha.data / "subscriptions.sqlite") != (beta.data / "subscriptions.sqlite")


# ---------------------------------------------------------------------------
# Test: knowledge store isolation
# ---------------------------------------------------------------------------


class TestKnowledgeStoreIsolation:
    """Two agents' knowledge DBs are fully independent."""

    def test_alpha_knowledge_invisible_to_beta(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            _, alpha_kb, *_ = _run_prepare_toolset_context(alpha)
            _, beta_kb, *_ = _run_prepare_toolset_context(beta)

            # Write a document visible only to alpha
            doc = alpha.knowledge / "secret.md"
            doc.write_text("Alpha's proprietary quantum algorithm.")
            index_file(alpha_kb, alpha.knowledge, doc)

            # Beta cannot find alpha's content via its own DB
            beta_results = search_knowledge(beta_kb, "quantum")
            assert len(beta_results) == 0

            # Alpha can find its own content
            alpha_results = search_knowledge(alpha_kb, "quantum")
            assert len(alpha_results) > 0

    def test_separate_knowledge_dbs_created(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            _, alpha_kb, *_ = _run_prepare_toolset_context(alpha)
            _, beta_kb, *_ = _run_prepare_toolset_context(beta)

            assert alpha_kb != beta_kb
            assert Path(alpha_kb).exists()
            assert Path(beta_kb).exists()


# ---------------------------------------------------------------------------
# Test: subscriptions isolation
# ---------------------------------------------------------------------------


class TestSubscriptionIsolation:
    """Two agents' subscription registries are fully independent."""

    def test_alpha_subscriptions_invisible_to_beta(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            _, _, alpha_sub, *_ = _run_prepare_toolset_context(alpha)
            _, _, beta_sub, *_ = _run_prepare_toolset_context(beta)

            alpha_sub.add("file", "alpha-private.py")

            assert len(alpha_sub.get_active()) == 1
            assert len(beta_sub.get_active()) == 0

    def test_beta_subscriptions_invisible_to_alpha(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            _, _, alpha_sub, *_ = _run_prepare_toolset_context(alpha)
            _, _, beta_sub, *_ = _run_prepare_toolset_context(beta)

            beta_sub.add("file", "beta-private.py")

            assert len(beta_sub.get_active()) == 1
            assert len(alpha_sub.get_active()) == 0


# ---------------------------------------------------------------------------
# Test: topics isolation
# ---------------------------------------------------------------------------


class TestTopicsIsolation:
    """Two agents' topic registries point to separate directories."""

    def test_alpha_topic_invisible_to_beta(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            _, _, _, alpha_tr, *_ = _run_prepare_toolset_context(alpha)
            _, _, _, beta_tr, *_ = _run_prepare_toolset_context(beta)

            from autopoiesis.topics.topic_manager import create_topic

            create_topic(alpha_tr, "alpha-secret-task", type="task", body="secret work")

            assert beta_tr.get_topic("alpha-secret-task") is None
            assert alpha_tr.get_topic("alpha-secret-task") is not None

    def test_separate_topics_dirs_created(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            alpha = resolve_agent_workspace("alpha")
            beta = resolve_agent_workspace("beta")

            _, _, _, alpha_tr, *_ = _run_prepare_toolset_context(alpha)
            _, _, _, beta_tr, *_ = _run_prepare_toolset_context(beta)

            assert alpha_tr.topics_dir != beta_tr.topics_dir
            assert alpha_tr.topics_dir.is_dir()
            assert beta_tr.topics_dir.is_dir()


# ---------------------------------------------------------------------------
# Test: toolset list is non-empty and returns a system prompt
# ---------------------------------------------------------------------------


class TestToolsetsReturnedCorrectly:
    """prepare_toolset_context returns a populated toolset list and system prompt."""

    def test_toolsets_non_empty(self, tmp_path: Path) -> None:
        with _AutopoiesisHome(tmp_path):
            paths = resolve_agent_workspace("toolset-test")
            _, _, _, _, toolsets, system_prompt = _run_prepare_toolset_context(paths)
            assert len(toolsets) > 0
            assert isinstance(system_prompt, str)
            assert len(system_prompt) > 0
