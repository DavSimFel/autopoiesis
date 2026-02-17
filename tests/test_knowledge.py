"""Tests for the file-based knowledge management system."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autopoiesis.store.knowledge import (
    CONTEXT_BUDGET_CHARS,
    SearchResult,
    build_backlink_index,
    ensure_journal_entry,
    format_search_results,
    init_knowledge_index,
    known_types,
    load_knowledge_context,
    parse_frontmatter,
    register_types,
    reindex_knowledge,
    sanitize_fts_query,
    search_knowledge,
    strip_frontmatter,
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


# ---------------------------------------------------------------------------
# Frontmatter parsing tests
# ---------------------------------------------------------------------------


class TestFrontmatter:
    def test_all_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text(
            "---\ntype: fact\ncreated: 2026-01-15T10:00:00+00:00\n"
            "modified: 2026-02-01T12:00:00+00:00\n---\n# Hello\n"
        )
        meta = parse_frontmatter(f.read_text(), f)
        assert meta.type == "fact"
        assert meta.created.year == 2026
        assert meta.created.month == 1
        assert meta.modified.month == 2

    def test_partial_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\ntype: decision\n---\n# Hello\n")
        meta = parse_frontmatter(f.read_text(), f)
        assert meta.type == "decision"
        assert meta.created is not None

    def test_missing_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("# No frontmatter\nJust content.\n")
        meta = parse_frontmatter(f.read_text(), f)
        assert meta.type == "note"

    def test_no_file_path(self) -> None:
        meta = parse_frontmatter("---\ntype: contact\n---\n# Hi\n")
        assert meta.type == "contact"

    def test_unknown_type_becomes_note(self) -> None:
        meta = parse_frontmatter("---\ntype: banana\n---\n# Hi\n")
        assert meta.type == "note"

    def test_strip_frontmatter(self) -> None:
        content = "---\ntype: fact\n---\n# Hello\nWorld\n"
        assert strip_frontmatter(content) == "# Hello\nWorld\n"

    def test_strip_no_frontmatter(self) -> None:
        content = "# Hello\nWorld\n"
        assert strip_frontmatter(content) == content

    def test_invalid_yaml(self) -> None:
        meta = parse_frontmatter("---\n: : :\n---\n# Bad\n")
        assert meta.type == "note"

    def test_date_string_without_tz(self) -> None:
        meta = parse_frontmatter("---\ncreated: 2026-03-01T08:00:00\n---\n")
        assert meta.created.tzinfo is not None


# ---------------------------------------------------------------------------
# Type registry tests
# ---------------------------------------------------------------------------


class TestTypeRegistry:
    def test_builtin_types(self) -> None:
        types = known_types()
        assert "fact" in types
        assert "note" in types
        assert "conversation" in types

    def test_register_custom(self) -> None:
        register_types({"custom_skill_type"})
        assert "custom_skill_type" in known_types()


# ---------------------------------------------------------------------------
# Filtered search tests
# ---------------------------------------------------------------------------


class TestFilteredSearch:
    def test_type_filter(self, knowledge_db: str, tmp_path: Path) -> None:
        root = tmp_path / "kroot"
        root.mkdir()
        (root / "a.md").write_text("---\ntype: fact\n---\nPython is great\n")
        (root / "b.md").write_text("---\ntype: decision\n---\nPython chosen over Ruby\n")
        init_knowledge_index(knowledge_db)
        reindex_knowledge(knowledge_db, root)

        all_results = search_knowledge(knowledge_db, "Python", knowledge_root=root)
        assert len(all_results) >= 2

        facts = search_knowledge(knowledge_db, "Python", type_filter="fact", knowledge_root=root)
        assert all(r.file_path == "a.md" for r in facts)

    def test_since_filter(self, knowledge_db: str, tmp_path: Path) -> None:
        root = tmp_path / "kroot"
        root.mkdir()
        (root / "old.md").write_text(
            "---\ntype: note\ncreated: 2020-01-01T00:00:00+00:00\n"
            "modified: 2020-01-01T00:00:00+00:00\n---\nOld content about dogs\n"
        )
        (root / "new.md").write_text(
            "---\ntype: note\ncreated: 2026-01-01T00:00:00+00:00\n"
            "modified: 2026-01-01T00:00:00+00:00\n---\nNew content about dogs\n"
        )
        init_knowledge_index(knowledge_db)
        reindex_knowledge(knowledge_db, root)

        since = datetime(2025, 1, 1, tzinfo=UTC)
        results = search_knowledge(knowledge_db, "dogs", since=since, knowledge_root=root)
        assert len(results) == 1
        assert results[0].file_path == "new.md"


# ---------------------------------------------------------------------------
# Wikilink backlink index tests
# ---------------------------------------------------------------------------


class TestBacklinkIndex:
    def test_basic_wikilinks(self, tmp_path: Path) -> None:
        root = tmp_path / "k"
        root.mkdir()
        (root / "a.md").write_text("See [[b]] and [[c]] for details.\n")
        (root / "b.md").write_text("Links to [[a]].\n")
        (root / "c.md").write_text("No links here.\n")

        index = build_backlink_index(root)
        assert "b" in index
        assert "a.md" in index["b"]
        assert "c" in index
        assert "a.md" in index["c"]
        assert "a" in index
        assert "b.md" in index["a"]

    def test_wikilink_with_alias(self, tmp_path: Path) -> None:
        root = tmp_path / "k"
        root.mkdir()
        (root / "a.md").write_text("See [[target|display text]].\n")
        index = build_backlink_index(root)
        assert "target" in index

    def test_empty_root(self, tmp_path: Path) -> None:
        index = build_backlink_index(tmp_path / "nonexistent")
        assert index == {}

    def test_performance_1k_files(self, tmp_path: Path) -> None:
        """Backlink index for 1K files should complete in <200ms."""
        import time

        root = tmp_path / "k"
        root.mkdir()
        for i in range(1000):
            (root / f"file{i}.md").write_text(
                f"Link to [[file{(i + 1) % 1000}]] and [[file{(i + 2) % 1000}]].\n"
            )

        start = time.monotonic()
        index = build_backlink_index(root)
        elapsed = time.monotonic() - start
        assert elapsed < 0.2, f"Backlink index took {elapsed:.3f}s (>200ms)"
        assert len(index) == 1000


# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_auto_loaded_context_still_works(self, knowledge_root: Path) -> None:
        """Context loading must work with files that have no frontmatter."""
        context = load_knowledge_context(knowledge_root)
        assert "SOUL" in context
        assert "FastAPI" in context

    def test_search_files_without_frontmatter(
        self, knowledge_db: str, knowledge_root: Path
    ) -> None:
        """Search must still find files that have no frontmatter."""
        reindex_knowledge(knowledge_db, knowledge_root)
        results = search_knowledge(knowledge_db, "FastAPI")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Migration frontmatter tests
# ---------------------------------------------------------------------------


class TestMigrationFrontmatter:
    def test_migration_adds_frontmatter(self, tmp_path: Path) -> None:
        import sqlite3

        from autopoiesis.store.knowledge_migration import migrate_memory_to_knowledge

        db = tmp_path / "mem.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE memory_entries (timestamp TEXT, summary TEXT, topics TEXT)")
        conn.execute("INSERT INTO memory_entries VALUES ('2026-01-01', 'Test entry', 'testing')")
        conn.commit()
        conn.close()

        kr = tmp_path / "knowledge"
        count = migrate_memory_to_knowledge(str(db), kr)
        assert count == 1

        content = (kr / "memory" / "MEMORY.md").read_text()
        assert content.startswith("---\n")
        assert "type: note" in content
        assert "Test entry" in content

    def test_migration_no_duplicate_frontmatter(self, tmp_path: Path) -> None:
        import sqlite3

        from autopoiesis.store.knowledge_migration import migrate_memory_to_knowledge

        db = tmp_path / "mem.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE memory_entries (timestamp TEXT, summary TEXT, topics TEXT)")
        conn.execute("INSERT INTO memory_entries VALUES ('2026-01-01', 'First', 'a')")
        conn.commit()
        conn.close()

        kr = tmp_path / "knowledge"
        (kr / "memory").mkdir(parents=True)
        (kr / "memory" / "MEMORY.md").write_text(
            "---\ntype: note\ncreated: 2026-01-01\nmodified: 2026-01-01\n---\n# Existing\n"
        )

        migrate_memory_to_knowledge(str(db), kr)
        content = (kr / "memory" / "MEMORY.md").read_text()
        assert content.count("---") == 2  # only the original pair
