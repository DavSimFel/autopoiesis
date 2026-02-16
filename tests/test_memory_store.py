"""Tests for the persistent memory store."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from store.memory import (
    combined_search,
    get_memory_file_snippet,
    init_memory_store,
    save_memory,
    search_memory,
    search_memory_files,
)


def _tmp_db() -> str:
    """Create a temporary database path and initialize the store."""
    fd, tmp = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    init_memory_store(tmp)
    return tmp


def test_save_and_search() -> None:
    db = _tmp_db()
    entry_id = save_memory(db, "Decided to use FastAPI for the web layer", ["architecture", "api"])
    hex_id_length = 32
    assert len(entry_id) == hex_id_length

    results = search_memory(db, "FastAPI", max_results=5)
    assert len(results) == 1
    assert results[0]["summary"] == "Decided to use FastAPI for the web layer"
    assert "architecture" in results[0]["topics"]


def test_search_ranking_multiple() -> None:
    db = _tmp_db()
    save_memory(db, "Chose PostgreSQL for persistence", ["database"])
    save_memory(db, "PostgreSQL schema migration strategy", ["database", "migration"])
    save_memory(db, "Redis caching layer added", ["cache"])

    results = search_memory(db, "PostgreSQL database", max_results=5)
    min_expected = 2
    assert len(results) >= min_expected
    summaries = [r["summary"] for r in results]
    assert any("PostgreSQL" in s for s in summaries)


def test_search_no_results() -> None:
    db = _tmp_db()
    save_memory(db, "Something about Python", ["python"])
    results = search_memory(db, "xyznonexistent", max_results=5)
    assert results == []


def test_search_empty_query() -> None:
    db = _tmp_db()
    results = search_memory(db, "", max_results=5)
    assert results == []


def test_file_search() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace)
        memory_md = root / "MEMORY.md"
        memory_md.write_text("# Memory\n\n## Decisions\n- Use SQLite for storage\n- Keep it simple")

        results = search_memory_files(root, "SQLite storage", max_results=5)
        assert len(results) >= 1
        assert results[0]["file"] == "MEMORY.md"
        assert "SQLite" in results[0]["snippet"]


def test_file_search_memory_dir() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace)
        mem_dir = root / "memory"
        mem_dir.mkdir()
        (mem_dir / "2025-01-15.md").write_text("## 2025-01-15\n- Deployed v2.0\n- Fixed auth bug")

        results = search_memory_files(root, "deployed", max_results=5)
        assert len(results) >= 1
        assert "2025-01-15.md" in results[0]["file"]


def test_get_memory_file_snippet() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace)
        (root / "MEMORY.md").write_text("line1\nline2\nline3\nline4\nline5")

        snippet = get_memory_file_snippet(root, "MEMORY.md", from_line=2, num_lines=3)
        assert snippet == "line2\nline3\nline4"


def test_get_memory_file_path_escape() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace)
        result = get_memory_file_snippet(root, "../../etc/passwd")
        assert "Error" in result


def test_combined_search() -> None:
    db = _tmp_db()
    save_memory(db, "Implemented user authentication with JWT", ["auth", "security"])

    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace)
        (root / "MEMORY.md").write_text("# Memory\n- JWT tokens expire after 1 hour")

        result = combined_search(db, root, "JWT authentication", max_results=5)
        assert "Database matches" in result
        assert "File matches" in result
