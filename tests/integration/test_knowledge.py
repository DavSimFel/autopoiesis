"""Section 5: Knowledge System integration tests."""

from __future__ import annotations

from pathlib import Path

from autopoiesis.store.knowledge import (
    load_knowledge_context,
    reindex_knowledge,
    search_knowledge,
)


class TestWriteAndSearch:
    """5.1 — Write file → search finds it."""

    def test_written_file_searchable(self, knowledge_db: str, knowledge_root: Path) -> None:
        auth_file = knowledge_root / "auth.md"
        auth_file.write_text("---\ntype: fact\n---\nJWT tokens expire after 24 hours.\n")
        reindex_knowledge(knowledge_db, knowledge_root)

        results = search_knowledge(knowledge_db, "JWT tokens")
        assert len(results) >= 1
        assert any("auth.md" in r.file_path for r in results)


class TestReindexPicksUpNewFiles:
    """5.2 — FTS index rebuilt on reindex."""

    def test_new_file_searchable_after_reindex(
        self, knowledge_db: str, knowledge_root: Path
    ) -> None:
        # Initial index — empty
        reindex_knowledge(knowledge_db, knowledge_root)
        assert search_knowledge(knowledge_db, "GraphQL") == []

        # Add file
        (knowledge_root / "api.md").write_text("GraphQL schema design patterns.\n")
        count = reindex_knowledge(knowledge_db, knowledge_root)
        assert count >= 1

        results = search_knowledge(knowledge_db, "GraphQL")
        assert len(results) >= 1


class TestAutoLoadedContext:
    """5.3 — Auto-loaded context works (identity, MEMORY.md, journal)."""

    def test_identity_files_loaded(self, knowledge_root: Path) -> None:
        (knowledge_root / "identity" / "SOUL.md").write_text("I am a helpful assistant.\n")
        (knowledge_root / "identity" / "USER.md").write_text("David is an engineer.\n")
        (knowledge_root / "identity" / "AGENTS.md").write_text("Be concise.\n")
        (knowledge_root / "identity" / "TOOLS.md").write_text("Use pytest.\n")
        (knowledge_root / "memory" / "MEMORY.md").write_text("Decided to use FastAPI.\n")

        context = load_knowledge_context(knowledge_root)
        assert "helpful assistant" in context
        assert "David" in context
        assert "FastAPI" in context


class TestDeleteAndReindex:
    """5.4 — Delete file → search stops finding it."""

    def test_deleted_file_not_searchable(self, knowledge_db: str, knowledge_root: Path) -> None:
        auth_file = knowledge_root / "auth.md"
        auth_file.write_text("JWT tokens expire after 24 hours.\n")
        reindex_knowledge(knowledge_db, knowledge_root)
        assert len(search_knowledge(knowledge_db, "JWT tokens")) >= 1

        # Delete and reindex
        auth_file.unlink()
        reindex_knowledge(knowledge_db, knowledge_root)
        assert search_knowledge(knowledge_db, "JWT tokens") == []
