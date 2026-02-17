"""Tests for the file-based knowledge management system."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from store.knowledge import (
    CONTEXT_BUDGET_CHARS,
    SearchResult,
    ensure_journal_entry,
    format_search_results,
    init_knowledge_index,
    load_knowledge_context,
    reindex_knowledge,
    sanitize_fts_query,
    search_knowledge,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def knowledge_db(tmp_path: Path) -> str:
    """Create a temporary knowledge index database."""
    db_path = str(tmp_path / "knowledge.sqlite")
    init_knowledge_index(db_path)
    return db_path


@pytest.fixture()
def knowledge_root(tmp_path: Path) -> Path:
    """Create a knowledge directory tree with sample content."""
    root = tmp_path / "knowledge"
    (root / "identity").mkdir(parents=True)
    (root / "memory").mkdir(parents=True)
    (root / "journal").mkdir(parents=True)
    (root / "projects").mkdir(parents=True)

    (root / "identity" / "SOUL.md").write_text("# SOUL\nI am a helpful coding assistant.\n")
    (root / "identity" / "USER.md").write_text("# USER\nDavid is a software engineer.\n")
    (root / "identity" / "AGENTS.md").write_text("# AGENTS\nBe concise and helpful.\n")
    (root / "identity" / "TOOLS.md").write_text("# TOOLS\nUse pytest for testing.\n")
    (root / "memory" / "MEMORY.md").write_text(
        "# Memory\n\n- Decided to use FastAPI\n- PostgreSQL for storage\n"
    )
    (root / "projects" / "autopoiesis.md").write_text(
        "# Autopoiesis\n\nAn autonomous coding agent built with PydanticAI.\n"
    )
    return root


# ---------------------------------------------------------------------------
# Indexing tests
# ---------------------------------------------------------------------------


class TestIndexing:
    def test_index_and_search(self, knowledge_db: str, knowledge_root: Path) -> None:
        count = reindex_knowledge(knowledge_db, knowledge_root)
        assert count >= 1

        results = search_knowledge(knowledge_db, "FastAPI")
        assert len(results) >= 1
        assert any("MEMORY" in r.file_path for r in results)

    def test_incremental_indexing(self, knowledge_db: str, knowledge_root: Path) -> None:
        first = reindex_knowledge(knowledge_db, knowledge_root)
        assert first >= 1

        # Second pass — nothing changed
        second = reindex_knowledge(knowledge_db, knowledge_root)
        assert second == 0

    def test_reindex_after_modification(self, knowledge_db: str, knowledge_root: Path) -> None:
        reindex_knowledge(knowledge_db, knowledge_root)

        # Modify a file
        mem = knowledge_root / "memory" / "MEMORY.md"
        mem.write_text("# Memory\n\n- Switched to SQLite for simplicity\n")
        # Touch to ensure mtime changes
        os.utime(mem, (mem.stat().st_atime + 1, mem.stat().st_mtime + 1))

        count = reindex_knowledge(knowledge_db, knowledge_root)
        assert count >= 1

        results = search_knowledge(knowledge_db, "SQLite simplicity")
        assert len(results) >= 1

    def test_deleted_files_removed_from_index(
        self, knowledge_db: str, knowledge_root: Path
    ) -> None:
        reindex_knowledge(knowledge_db, knowledge_root)

        # Delete a file
        (knowledge_root / "projects" / "autopoiesis.md").unlink()
        reindex_knowledge(knowledge_db, knowledge_root)

        results = search_knowledge(knowledge_db, "autopoiesis PydanticAI")
        assert len(results) == 0

    def test_index_nonexistent_root(self, knowledge_db: str, tmp_path: Path) -> None:
        count = reindex_knowledge(knowledge_db, tmp_path / "nonexistent")
        assert count == 0


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


class TestSearch:
    def test_empty_query(self, knowledge_db: str) -> None:
        results = search_knowledge(knowledge_db, "")
        assert results == []

    def test_no_results(self, knowledge_db: str, knowledge_root: Path) -> None:
        reindex_knowledge(knowledge_db, knowledge_root)
        results = search_knowledge(knowledge_db, "xyznonexistent")
        assert results == []

    def test_result_structure(self, knowledge_db: str, knowledge_root: Path) -> None:
        reindex_knowledge(knowledge_db, knowledge_root)
        results = search_knowledge(knowledge_db, "PostgreSQL")
        assert len(results) >= 1
        r = results[0]
        assert isinstance(r, SearchResult)
        assert r.file_path
        assert r.line_start >= 1
        assert r.line_end >= r.line_start
        assert r.snippet
        assert isinstance(r.score, float)

    def test_format_results_empty(self) -> None:
        assert format_search_results([]) == "No results found."

    def test_format_results(self) -> None:
        results = [
            SearchResult("memory/MEMORY.md", 1, 3, "some snippet", -1.5),
        ]
        formatted = format_search_results(results)
        assert "memory/MEMORY.md" in formatted
        assert "some snippet" in formatted

    def test_limit_respected(self, knowledge_db: str, knowledge_root: Path) -> None:
        reindex_knowledge(knowledge_db, knowledge_root)
        results = search_knowledge(knowledge_db, "the", limit=1)
        assert len(results) <= 1


# ---------------------------------------------------------------------------
# Context injection tests
# ---------------------------------------------------------------------------


class TestContextInjection:
    def test_loads_identity_files(self, knowledge_root: Path) -> None:
        context = load_knowledge_context(knowledge_root)
        assert "SOUL" in context
        assert "USER" in context
        assert "AGENTS" in context
        assert "TOOLS" in context

    def test_loads_memory(self, knowledge_root: Path) -> None:
        context = load_knowledge_context(knowledge_root)
        assert "FastAPI" in context

    def test_loads_todays_journal(self, knowledge_root: Path) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        journal = knowledge_root / "journal" / f"{today}.md"
        journal.write_text(f"# {today}\n\n- Important meeting with stakeholders\n")

        context = load_knowledge_context(knowledge_root)
        assert "Important meeting" in context

    def test_budget_cap_enforced(self, knowledge_root: Path) -> None:
        # Write a huge SOUL.md
        (knowledge_root / "identity" / "SOUL.md").write_text("x" * 30_000)

        context = load_knowledge_context(knowledge_root)
        assert len(context) <= CONTEXT_BUDGET_CHARS + 500  # small overhead for separator/truncation

    def test_nonexistent_root(self, tmp_path: Path) -> None:
        context = load_knowledge_context(tmp_path / "nonexistent")
        assert context == ""


# ---------------------------------------------------------------------------
# Journal tests
# ---------------------------------------------------------------------------


class TestJournal:
    def test_creates_journal_entry(self, knowledge_root: Path) -> None:
        path = ensure_journal_entry(knowledge_root)
        assert path.exists()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert today in path.name
        content = path.read_text()
        assert today in content

    def test_idempotent(self, knowledge_root: Path) -> None:
        path1 = ensure_journal_entry(knowledge_root)
        path1.write_text("# Custom content\n")
        path2 = ensure_journal_entry(knowledge_root)
        assert path1 == path2
        assert path2.read_text() == "# Custom content\n"


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# FTS sanitize query tests
# ---------------------------------------------------------------------------


class TestSanitizeFtsQuery:
    def test_normal_query(self) -> None:
        result = sanitize_fts_query("hello world")
        assert "hello*" in result
        assert "world*" in result

    def test_fts_operators_stripped(self) -> None:
        result = sanitize_fts_query("hello AND world OR NOT test NEAR foo")
        # FTS keywords should be removed
        assert "AND" not in result.split()
        assert "OR" not in result.replace(" OR ", "|").split("|")  # OR is used as joiner
        assert "NOT*" not in result
        assert "NEAR*" not in result
        assert "hello*" in result
        assert "world*" in result
        assert "foo*" in result

    def test_special_characters_removed(self) -> None:
        result = sanitize_fts_query('hello "world" (test) {foo} [bar]')
        assert '"' not in result
        assert "(" not in result
        assert "{" not in result
        assert "[" not in result
        assert "hello*" in result
        assert "world*" in result

    def test_empty_string(self) -> None:
        assert sanitize_fts_query("") == ""

    def test_only_operators(self) -> None:
        assert sanitize_fts_query("AND OR NOT NEAR") == ""

    def test_only_special_chars(self) -> None:
        assert sanitize_fts_query("!@#$%^&*()") == ""

    def test_very_long_string(self) -> None:
        long_query = "word " * 1000
        result = sanitize_fts_query(long_query)
        assert isinstance(result, str)
        assert "word*" in result

    def test_unicode_tokens(self) -> None:
        result = sanitize_fts_query("über café naïve")
        assert result  # should produce some tokens
        assert "ber*" in result or "über*" in result  # depends on \w matching

    def test_mixed_case_operators(self) -> None:
        # Operators are matched case-insensitively via .upper()
        result = sanitize_fts_query("and or not near")
        assert result == ""  # all are FTS keywords regardless of case

    def test_single_word(self) -> None:
        result = sanitize_fts_query("python")
        assert result == "python*"

    def test_fts_injection_attempt(self) -> None:
        # Attempt column filter syntax
        result = sanitize_fts_query('file_path:"../../etc/passwd"')
        assert "file_path" in result  # treated as normal word
        assert "passwd" in result
        assert ":" not in result
        assert '"' not in result
