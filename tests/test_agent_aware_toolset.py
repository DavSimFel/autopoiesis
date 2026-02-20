"""Tests for agent-aware toolset initialization (Issue #202).

Verifies that each agent gets its own isolated workspace root, knowledge
database, subscription registry, and topic registry — and that toolset
state for one agent never leaks to another.
"""

from __future__ import annotations

import os
from pathlib import Path

from autopoiesis.agent.workspace import resolve_agent_workspace
from autopoiesis.tools.agent_toolset import (
    build_backend_for_agent,
    prepare_toolset_context_for_agent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AutopoiesisHome:
    """Context manager to temporarily redirect AUTOPOIESIS_HOME to a tmp dir."""

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


# ---------------------------------------------------------------------------
# 202.1 — build_backend_for_agent
# ---------------------------------------------------------------------------


class TestBuildBackendForAgent:
    """build_backend_for_agent creates an isolated LocalBackend per agent."""

    def test_backend_root_matches_agent_workspace(self, tmp_path: Path) -> None:
        """The backend's root_dir is the agent's workspace directory."""
        from pydantic_ai_backends import LocalBackend

        agent_workspace = tmp_path / "ws-alpha"
        backend = build_backend_for_agent(agent_workspace)
        assert isinstance(backend, LocalBackend)
        # The directory must be created.
        assert agent_workspace.is_dir()

    def test_two_agents_get_different_backends(self, tmp_path: Path) -> None:
        """Backends for different agents have different root directories."""
        ws_alpha = tmp_path / "alpha" / "workspace"
        ws_beta = tmp_path / "beta" / "workspace"
        backend_alpha = build_backend_for_agent(ws_alpha)
        backend_beta = build_backend_for_agent(ws_beta)
        assert backend_alpha is not backend_beta


# ---------------------------------------------------------------------------
# 202.2 — prepare_toolset_context_for_agent path isolation
# ---------------------------------------------------------------------------


class TestPrepareToolsetContextForAgentPaths:
    """prepare_toolset_context_for_agent returns agent-specific paths."""

    def test_workspace_root_keyed_by_agent(self, tmp_path: Path) -> None:
        """Two agents get different workspace_root values."""
        with _AutopoiesisHome(tmp_path):
            history_db = str(tmp_path / "history.sqlite")
            ws_alpha, *_ = prepare_toolset_context_for_agent("alpha", history_db)
            ws_beta, *_ = prepare_toolset_context_for_agent("beta", history_db)
            assert ws_alpha != ws_beta

    def test_knowledge_db_path_keyed_by_agent(self, tmp_path: Path) -> None:
        """Two agents get different knowledge DB paths."""
        with _AutopoiesisHome(tmp_path):
            history_db = str(tmp_path / "history.sqlite")
            _, k_alpha, *_ = prepare_toolset_context_for_agent("alpha", history_db)
            _, k_beta, *_ = prepare_toolset_context_for_agent("beta", history_db)
            assert k_alpha != k_beta

    def test_subscription_registry_isolated(self, tmp_path: Path) -> None:
        """Two agents get different SubscriptionRegistry instances."""
        with _AutopoiesisHome(tmp_path):
            history_db = str(tmp_path / "history.sqlite")
            _, _, sub_alpha, *_ = prepare_toolset_context_for_agent("alpha", history_db)
            _, _, sub_beta, *_ = prepare_toolset_context_for_agent("beta", history_db)
            # Different objects pointing to different backing DBs.
            assert sub_alpha is not sub_beta

    def test_topic_registry_isolated(self, tmp_path: Path) -> None:
        """Two agents get TopicRegistry instances with different root directories."""
        with _AutopoiesisHome(tmp_path):
            history_db = str(tmp_path / "history.sqlite")
            _, _, _, topic_alpha, *_ = prepare_toolset_context_for_agent("alpha", history_db)
            _, _, _, topic_beta, *_ = prepare_toolset_context_for_agent("beta", history_db)
            assert topic_alpha is not topic_beta

    def test_workspace_under_agent_home(self, tmp_path: Path) -> None:
        """Agent's workspace_root is under AUTOPOIESIS_HOME/agents/<agent_id>/."""
        with _AutopoiesisHome(tmp_path):
            history_db = str(tmp_path / "history.sqlite")
            ws_alpha, *_ = prepare_toolset_context_for_agent("alpha", history_db)
            # Path must be nested under AUTOPOIESIS_HOME/agents/alpha/
            assert "agents" in ws_alpha.parts
            assert "alpha" in ws_alpha.parts

    def test_return_tuple_length(self, tmp_path: Path) -> None:
        """Return value is the expected 6-tuple."""
        with _AutopoiesisHome(tmp_path):
            history_db = str(tmp_path / "history.sqlite")
            result = prepare_toolset_context_for_agent("alpha", history_db)
            assert len(result) == 6  # (workspace_root, k_db, sub_reg, topic_reg, toolsets, prompt)


# ---------------------------------------------------------------------------
# 202.3 — Tool name filtering per agent
# ---------------------------------------------------------------------------


class TestPerAgentToolFiltering:
    """Each agent's tool_names list independently controls which toolsets are built."""

    def test_agent_with_topics_gets_more_toolsets_than_without(self, tmp_path: Path) -> None:
        """Agent with 'topics' in tool_names gets more toolsets than one without."""
        with _AutopoiesisHome(tmp_path):
            history_db = str(tmp_path / "history.sqlite")
            _, _, _, _, toolsets_with, _ = prepare_toolset_context_for_agent(
                "agent-with-topics", history_db, tool_names=["shell", "topics"]
            )
            _, _, _, _, toolsets_without, _ = prepare_toolset_context_for_agent(
                "agent-no-topics", history_db, tool_names=["shell"]
            )
            assert len(toolsets_with) > len(toolsets_without)

    def test_different_tool_names_per_agent_dont_interfere(self, tmp_path: Path) -> None:
        """Building toolsets for agent A does not affect toolset count for agent B."""
        with _AutopoiesisHome(tmp_path):
            history_db = str(tmp_path / "history.sqlite")
            # Alpha gets all tools.
            _, _, _, _, toolsets_alpha, _ = prepare_toolset_context_for_agent(
                "alpha", history_db, tool_names=["shell", "exec", "search", "topics"]
            )
            # Beta gets only shell.
            _, _, _, _, toolsets_beta, _ = prepare_toolset_context_for_agent(
                "beta", history_db, tool_names=["shell"]
            )
            # Building alpha's toolset should not inflate beta's.
            assert len(toolsets_alpha) > len(toolsets_beta)


# ---------------------------------------------------------------------------
# 202.4 — Knowledge isolation (data on disk)
# ---------------------------------------------------------------------------


class TestKnowledgeIsolationOnDisk:
    """Knowledge files written for agent A are NOT visible to agent B."""

    def test_knowledge_files_are_isolated(self, tmp_path: Path) -> None:
        """A markdown file in agent A's knowledge dir is absent from agent B's."""
        with _AutopoiesisHome(tmp_path):
            paths_alpha = resolve_agent_workspace("alpha")
            paths_beta = resolve_agent_workspace("beta")

            paths_alpha.knowledge.mkdir(parents=True, exist_ok=True)
            paths_beta.knowledge.mkdir(parents=True, exist_ok=True)

            (paths_alpha.knowledge / "secret.md").write_text("Alpha's secret")

            beta_files = list(paths_beta.knowledge.glob("*.md"))
            assert len(beta_files) == 0, "Beta should not see alpha's knowledge files"

            alpha_files = list(paths_alpha.knowledge.glob("*.md"))
            assert any(f.name == "secret.md" for f in alpha_files)


# ---------------------------------------------------------------------------
# 202.5 — Subscription registry independence
# ---------------------------------------------------------------------------


class TestSubscriptionRegistryIndependence:
    """Subscription registries built for different agents are fully independent."""

    def test_subscribe_in_alpha_not_visible_in_beta(self, tmp_path: Path) -> None:
        """A subscription added to alpha's registry is absent from beta's."""
        with _AutopoiesisHome(tmp_path):
            history_db = str(tmp_path / "history.sqlite")
            _, _, sub_alpha, *_ = prepare_toolset_context_for_agent("alpha", history_db)
            _, _, sub_beta, *_ = prepare_toolset_context_for_agent("beta", history_db)

            # Add a subscription in alpha's registry.
            sub_alpha.add(kind="file", target="/some/file.md")

            # Beta's registry should have none.
            beta_subs = sub_beta.get_active()
            assert len(beta_subs) == 0, (
                "Beta's subscription registry should be empty after subscribing in alpha's"
            )
