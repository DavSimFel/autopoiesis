"""Section 6: Agent Isolation (Multi-Agent) integration tests.

Tests verify that agents get isolated directory trees and cannot see
each other's knowledge, topics, or state. Blocked on #146 Phase A.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from autopoiesis.agent.workspace import resolve_agent_workspace


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


@pytest.mark.skip(reason="Blocked on #146 Phase A — full multi-agent runtime not implemented")
class TestAgentKnowledgeIsolation:
    """6.2 — Agent A cannot see Agent B knowledge."""

    def test_knowledge_search_isolated(self, tmp_path: Path) -> None:
        # Agent A writes to its knowledge/
        # Agent B searches → no results from A
        raise NotImplementedError("Multi-agent knowledge isolation not yet implemented")


@pytest.mark.skip(reason="Blocked on #146 Phase A — full multi-agent runtime not implemented")
class TestAgentTopicIsolation:
    """6.3 — Agent A cannot see Agent B topics."""

    def test_topic_listing_isolated(self, tmp_path: Path) -> None:
        # Agent A creates topic "my-task.md"
        # Agent B lists topics → "my-task" not visible
        raise NotImplementedError("Multi-agent topic isolation not yet implemented")


@pytest.mark.skip(reason="Blocked on #146 Phase A — DBOS shared system DB not implemented")
class TestSharedDBOS:
    """6.4 — Shared DBOS system DB."""

    def test_agents_share_system_db(self, tmp_path: Path) -> None:
        # Two agents query DBOS → same system DB, different agent_ids
        raise NotImplementedError("Shared DBOS not yet implemented")


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
