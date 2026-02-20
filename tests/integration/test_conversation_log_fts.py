"""Integration test: FTS5 indexes conversation log files.

Verifies that after ``append_turn`` writes a log file, the FTS5 knowledge
index is updated so that ``search_knowledge`` can find the logged content.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from autopoiesis.store.conversation_log import append_turn
from autopoiesis.store.knowledge import init_knowledge_index, search_knowledge

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def knowledge_root(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    root.mkdir()
    return root


@pytest.fixture()
def knowledge_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "knowledge.sqlite")
    init_knowledge_index(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_request(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _assistant_response(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestFts5Integration:
    def test_log_content_searchable_after_append(
        self, knowledge_root: Path, knowledge_db: str
    ) -> None:
        """Content written by append_turn is immediately searchable via FTS5."""
        unique_phrase = "zymurgy_fermentation_quantum_2026"
        messages = [
            _user_request(f"Tell me about {unique_phrase}."),
            _assistant_response(f"Great topic! {unique_phrase} is fascinating."),
        ]

        ts = datetime(2026, 2, 20, 14, 0, 0, tzinfo=UTC)
        append_turn(knowledge_root, knowledge_db, "fts-agent", messages, timestamp=ts)

        results = search_knowledge(knowledge_db, unique_phrase)
        assert len(results) >= 1
        assert any("fts-agent" in r.file_path for r in results)

    def test_log_file_path_in_results(
        self, knowledge_root: Path, knowledge_db: str
    ) -> None:
        """Search results reference the correct log file path."""
        messages = [
            _user_request("Unique content about tachyon_propulsion_system_xyz."),
        ]
        ts = datetime(2026, 2, 20, 9, 0, 0, tzinfo=UTC)
        append_turn(knowledge_root, knowledge_db, "path-agent", messages, timestamp=ts)

        results = search_knowledge(knowledge_db, "tachyon_propulsion_system_xyz")
        assert len(results) >= 1
        assert any("logs/path-agent/2026-02-20.md" in r.file_path for r in results)

    def test_multiple_agents_indexed_separately(
        self, knowledge_root: Path, knowledge_db: str
    ) -> None:
        """Multiple agents each get their own log files, all indexed correctly."""
        ts = datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC)

        append_turn(
            knowledge_root,
            knowledge_db,
            "alpha-agent",
            [_user_request("What is the zeta_mechanism_42?")],
            timestamp=ts,
        )
        append_turn(
            knowledge_root,
            knowledge_db,
            "beta-agent",
            [_user_request("Explain the delta_protocol_99.")],
            timestamp=ts,
        )

        zeta_results = search_knowledge(knowledge_db, "zeta_mechanism_42")
        delta_results = search_knowledge(knowledge_db, "delta_protocol_99")

        assert any("alpha-agent" in r.file_path for r in zeta_results)
        assert any("beta-agent" in r.file_path for r in delta_results)

    def test_updated_log_reindexed(
        self, knowledge_root: Path, knowledge_db: str
    ) -> None:
        """A second append_turn on the same day re-indexes the updated file."""
        ts1 = datetime(2026, 2, 20, 8, 0, 0, tzinfo=UTC)
        ts2 = datetime(2026, 2, 20, 9, 0, 0, tzinfo=UTC)
        unique_first = "sigma_convergence_alpha_111"
        unique_second = "omega_divergence_beta_222"

        append_turn(
            knowledge_root,
            knowledge_db,
            "reindex-agent",
            [_user_request(unique_first)],
            timestamp=ts1,
        )
        append_turn(
            knowledge_root,
            knowledge_db,
            "reindex-agent",
            [_user_request(unique_second)],
            timestamp=ts2,
        )

        results_first = search_knowledge(knowledge_db, unique_first)
        results_second = search_knowledge(knowledge_db, unique_second)

        assert len(results_first) >= 1
        assert len(results_second) >= 1

    def test_log_files_found_under_logs_subdir(
        self, knowledge_root: Path, knowledge_db: str
    ) -> None:
        """Log files live under knowledge/logs/ and are indexed at that path."""
        ts = datetime(2026, 2, 20, 7, 0, 0, tzinfo=UTC)
        messages = [_user_request("Testing subdir_indexing_verification_xyz.")]

        append_turn(knowledge_root, knowledge_db, "subdir-agent", messages, timestamp=ts)

        results = search_knowledge(knowledge_db, "subdir_indexing_verification_xyz")
        file_paths = [r.file_path for r in results]
        assert any(p.startswith("logs/") for p in file_paths)
