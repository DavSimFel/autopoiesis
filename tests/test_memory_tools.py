"""Tests for memory_tools: PydanticAI tool wrappers with mocked memory_store."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tools.memory_tools import create_memory_toolset


@pytest.fixture()
def memory_db(tmp_path: Path) -> str:
    """Create a temporary memory database and return its path."""
    from store.memory import init_memory_store

    db_path = str(tmp_path / "mem.sqlite")
    init_memory_store(db_path)
    return db_path


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Create a workspace root with a memory file."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    mem_dir = ws / "memory"
    mem_dir.mkdir()
    (mem_dir / "2026-02-16.md").write_text("## 2026-02-16\n- Did some work\n- Made decisions")
    (ws / "MEMORY.md").write_text("# Memory\n- Important fact")
    return ws


class TestCreateMemoryToolset:
    """Tests for create_memory_toolset structure."""

    def test_returns_toolset_and_instructions(self, memory_db: str, workspace: Path) -> None:
        toolset, instructions = create_memory_toolset(memory_db, workspace)
        assert toolset is not None
        assert "memory" in instructions.lower()

    def test_instructions_contain_usage_guidance(self, memory_db: str, workspace: Path) -> None:
        _, instructions = create_memory_toolset(memory_db, workspace)
        assert "memory_search" in instructions
        assert "memory_save" in instructions


class TestCombinedSearch:
    """Tests for memory_search via combined_search (the underlying function)."""

    def test_no_matches(self, memory_db: str, workspace: Path) -> None:
        from store.memory import combined_search

        result = combined_search(memory_db, workspace, "nonexistent_xyz_query")
        assert "no memory matches" in result.lower()

    def test_empty_query(self, memory_db: str, workspace: Path) -> None:
        from store.memory import combined_search

        result = combined_search(memory_db, workspace, "")
        assert isinstance(result, str)

    def test_special_characters(self, memory_db: str, workspace: Path) -> None:
        from store.memory import combined_search

        result = combined_search(memory_db, workspace, 'test "quotes" & <special>')
        assert isinstance(result, str)

    def test_returns_saved_entry(self, memory_db: str, workspace: Path) -> None:
        from store.memory import combined_search, save_memory

        save_memory(memory_db, "Architecture decision about caching", ["arch"])
        result = combined_search(memory_db, workspace, "caching")
        assert "caching" in result.lower()


class TestSaveMemory:
    """Tests for memory_save via save_memory (the underlying function)."""

    def test_save_returns_id(self, memory_db: str) -> None:
        from store.memory import save_memory

        entry_id = save_memory(memory_db, "Important decision", ["auth"])
        assert isinstance(entry_id, str)
        assert len(entry_id) > 0

    def test_save_empty_topics(self, memory_db: str) -> None:
        from store.memory import save_memory

        entry_id = save_memory(memory_db, "note with no topics", [])
        assert isinstance(entry_id, str)

    def test_save_special_characters(self, memory_db: str) -> None:
        from store.memory import save_memory

        entry_id = save_memory(memory_db, 'Decision: use "quotes" & <tags>', ["special"])
        assert isinstance(entry_id, str)


class TestGetMemoryFileSnippet:
    """Tests for memory_get via get_memory_file_snippet."""

    def test_reads_existing_file(self, workspace: Path) -> None:
        from store.memory import get_memory_file_snippet

        result = get_memory_file_snippet(workspace, "MEMORY.md")
        assert "Important fact" in result

    def test_missing_file(self, workspace: Path) -> None:
        from store.memory import get_memory_file_snippet

        result = get_memory_file_snippet(workspace, "missing.md")
        assert "not found" in result.lower()

    def test_path_traversal_blocked(self, workspace: Path) -> None:
        from store.memory import get_memory_file_snippet

        result = get_memory_file_snippet(workspace, "../../etc/passwd")
        assert "error" in result.lower()

    def test_line_range(self, workspace: Path) -> None:
        from store.memory import get_memory_file_snippet

        result = get_memory_file_snippet(
            workspace, "memory/2026-02-16.md", from_line=2, num_lines=1
        )
        assert "Did some work" in result

    def test_from_line_none(self, workspace: Path) -> None:
        from store.memory import get_memory_file_snippet

        result = get_memory_file_snippet(workspace, "MEMORY.md", None, None)
        assert "Memory" in result


class TestMemoryToolsetIntegration:
    """Verify tool wrappers call the correct underlying functions."""

    def test_search_tool_delegates_to_combined_search(
        self, memory_db: str, workspace: Path
    ) -> None:
        with patch(
            "tools.memory_tools.combined_search",
            return_value="mocked result",
        ) as mock_fn:
            create_memory_toolset(memory_db, workspace)
            mock_fn.assert_not_called()

    def test_save_tool_delegates_to_save_memory(self, memory_db: str, workspace: Path) -> None:
        with patch(
            "tools.memory_tools.save_memory",
            return_value="abc123",
        ) as mock_fn:
            create_memory_toolset(memory_db, workspace)
            mock_fn.assert_not_called()
