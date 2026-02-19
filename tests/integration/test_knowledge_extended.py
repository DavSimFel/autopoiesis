"""Extended knowledge integration tests — FTS sanitization, filters, budget, journal."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autopoiesis.store.knowledge import (
    CONTEXT_BUDGET_CHARS,
    ensure_journal_entry,
    index_file,
    init_knowledge_index,
    load_knowledge_context,
    sanitize_fts_query,
    search_knowledge,
)


class TestFTSSanitization:
    """FTS5 query sanitization edge cases."""

    def test_empty_query_returns_empty(self) -> None:
        assert sanitize_fts_query("") == ""

    def test_only_special_chars_returns_empty(self) -> None:
        assert sanitize_fts_query("!@#$%^&*()") == ""

    def test_fts_keywords_stripped(self) -> None:
        result = sanitize_fts_query("AND OR NOT")
        assert result == ""

    def test_normal_query_produces_or_tokens(self) -> None:
        result = sanitize_fts_query("hello world")
        assert "hello*" in result
        assert "world*" in result
        assert "OR" in result

    def test_mixed_keywords_and_words(self) -> None:
        result = sanitize_fts_query("find AND match")
        assert "find*" in result
        assert "match*" in result
        # AND keyword should be stripped
        assert result.count("AND") == 0

    def test_empty_query_search_returns_empty(self, knowledge_db: str) -> None:
        results = search_knowledge(knowledge_db, "")
        assert results == []

    def test_special_chars_search_returns_empty(self, knowledge_db: str) -> None:
        results = search_knowledge(knowledge_db, "!@#$")
        assert results == []


class TestMetadataFilters:
    """search_knowledge type_filter and since parameters."""

    def test_type_filter(self, tmp_path: Path) -> None:
        knowledge_root = tmp_path / "knowledge"
        knowledge_root.mkdir()
        db_path = str(tmp_path / "knowledge.sqlite")
        init_knowledge_index(db_path)

        fact_file = knowledge_root / "fact.md"
        fact_file.write_text("---\ntype: fact\n---\nPython is a programming language.\n")
        index_file(db_path, knowledge_root, fact_file)

        note_file = knowledge_root / "note.md"
        note_file.write_text("---\ntype: note\n---\nPython notes from today.\n")
        index_file(db_path, knowledge_root, note_file)

        # Filter by type=fact
        results = search_knowledge(
            db_path, "Python", type_filter="fact", knowledge_root=knowledge_root
        )
        assert all(r.file_path == "fact.md" for r in results)

    @pytest.mark.xfail(
        reason="Bug: _parse_datetime doesn't handle datetime.date from YAML (yaml.safe_load "
        "parses '2020-01-01' as date, not datetime/str). Frontmatter dates silently ignored.",
        strict=True,
    )
    def test_since_filter(self, tmp_path: Path) -> None:
        knowledge_root = tmp_path / "knowledge"
        knowledge_root.mkdir()
        db_path = str(tmp_path / "knowledge.sqlite")
        init_knowledge_index(db_path)

        # Write both with explicit created AND modified in frontmatter
        old_file = knowledge_root / "old.md"
        old_file.write_text(
            "---\ntype: note\ncreated: 2020-01-01\nmodified: 2020-01-01\n---\nOld Python notes.\n"
        )
        index_file(db_path, knowledge_root, old_file)

        new_file = knowledge_root / "new.md"
        new_file.write_text(
            "---\ntype: note\ncreated: 2025-06-01\nmodified: 2025-06-01\n---\nNew Python notes.\n"
        )
        index_file(db_path, knowledge_root, new_file)

        since = datetime(2024, 1, 1, tzinfo=UTC)
        results = search_knowledge(db_path, "Python", since=since, knowledge_root=knowledge_root)
        assert any(r.file_path == "new.md" for r in results)
        assert not any(r.file_path == "old.md" for r in results)


class TestContextBudgetTruncation:
    """load_knowledge_context respects CONTEXT_BUDGET_CHARS."""

    def test_large_file_truncated(self, tmp_path: Path) -> None:
        knowledge_root = tmp_path / "knowledge"
        for sub in ("identity", "memory", "journal"):
            (knowledge_root / sub).mkdir(parents=True)

        # Write an identity file larger than budget
        large_content = "x" * (CONTEXT_BUDGET_CHARS + 5000)
        (knowledge_root / "identity" / "SOUL.md").write_text(large_content)

        context = load_knowledge_context(knowledge_root)
        assert len(context) <= CONTEXT_BUDGET_CHARS + 200  # small overhead for truncation marker
        assert "truncated" in context


class TestJournalAutoLoad:
    """ensure_journal_entry creates today's journal file."""

    def test_journal_created(self, tmp_path: Path) -> None:
        knowledge_root = tmp_path / "knowledge"
        knowledge_root.mkdir()

        path = ensure_journal_entry(knowledge_root)
        assert path.exists()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert today in path.name
        content = path.read_text()
        assert today in content

    def test_journal_idempotent(self, tmp_path: Path) -> None:
        knowledge_root = tmp_path / "knowledge"
        knowledge_root.mkdir()

        path1 = ensure_journal_entry(knowledge_root)
        path1.write_text("custom content")
        path2 = ensure_journal_entry(knowledge_root)
        assert path1 == path2
        assert path2.read_text() == "custom content"

    def test_journal_loaded_in_context(self, tmp_path: Path) -> None:
        knowledge_root = tmp_path / "knowledge"
        for sub in ("identity", "memory", "journal"):
            (knowledge_root / sub).mkdir(parents=True)

        path = ensure_journal_entry(knowledge_root)
        path.write_text("# Today\nImportant meeting notes.")

        context = load_knowledge_context(knowledge_root)
        assert "Important meeting notes" in context
