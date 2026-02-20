"""Tests for store/result_store.py -- persistent tool/shell output storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autopoiesis.store.result_store import (
    get_result,
    rotate_results,
    store_shell_output,
    store_tool_result,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """A fresh agent tmp/ directory for each test."""
    d = tmp_path / "tmp"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# store_tool_result
# ---------------------------------------------------------------------------


def test_store_tool_result_creates_file(tmp_dir: Path) -> None:
    path = store_tool_result(tmp_dir, "read", "hello world", {"tool_call_id": "tc1"})
    assert path.exists()
    assert path.suffix == ".out"


def test_store_tool_result_date_directory(tmp_dir: Path) -> None:
    path = store_tool_result(tmp_dir, "search", "results", {})
    today = datetime.now(UTC).date().isoformat()
    assert path.parent.name == today
    assert path.parent.parent.name == "tool-results"


def test_store_tool_result_content_readable(tmp_dir: Path) -> None:
    content = "full output here"
    path = store_tool_result(tmp_dir, "mytool", content, {"k": "v"})
    stored = path.read_text(encoding="utf-8")
    assert content in stored
    assert "mytool" in stored


def test_get_result_reads_back_tool_result(tmp_dir: Path) -> None:
    content = "some big output"
    path = store_tool_result(tmp_dir, "tool", content, {})
    assert content in get_result(path)


# ---------------------------------------------------------------------------
# store_shell_output
# ---------------------------------------------------------------------------


def test_store_shell_output_creates_file(tmp_dir: Path) -> None:
    path = store_shell_output(tmp_dir, "echo hi", "hi\n", "", 0, 42)
    assert path.exists()
    assert path.suffix == ".log"


def test_store_shell_output_date_directory(tmp_dir: Path) -> None:
    path = store_shell_output(tmp_dir, "ls", "a\nb\n", "", 0, 10)
    today = datetime.now(UTC).date().isoformat()
    assert path.parent.name == today
    assert path.parent.parent.name == "shell"


def test_store_shell_output_content(tmp_dir: Path) -> None:
    path = store_shell_output(tmp_dir, "pwd", "/workspace", "warning", 0, 5)
    stored = path.read_text(encoding="utf-8")
    assert "pwd" in stored
    assert "/workspace" in stored
    assert "warning" in stored
    assert "[stdout]" in stored
    assert "[stderr]" in stored


def test_get_result_reads_back_shell_output(tmp_dir: Path) -> None:
    path = store_shell_output(tmp_dir, "date", "2026-02-20", "", 0, 1)
    assert "2026-02-20" in get_result(path)


# ---------------------------------------------------------------------------
# rotate_results
# ---------------------------------------------------------------------------


def _make_date_dir(base: Path, days_ago: int, size_bytes: int = 0) -> Path:
    """Create a dated subdirectory under base with an optional dummy file."""
    d = datetime.now(UTC).date() - timedelta(days=days_ago)
    date_dir = base / d.isoformat()
    date_dir.mkdir(parents=True, exist_ok=True)
    if size_bytes:
        (date_dir / "data.bin").write_bytes(b"x" * size_bytes)
    return date_dir


def test_rotate_results_no_op_when_no_tmp(tmp_path: Path) -> None:
    deleted = rotate_results(tmp_path / "nonexistent", 14, 500)
    assert deleted == []


def test_rotate_results_deletes_old_dirs(tmp_dir: Path) -> None:
    subtree = tmp_dir / "tool-results"
    old = _make_date_dir(subtree, days_ago=20)
    recent = _make_date_dir(subtree, days_ago=3)

    deleted = rotate_results(tmp_dir, retention_days=14, max_size_mb=500)

    assert old in deleted
    assert not old.exists()
    assert recent.exists()


def test_rotate_results_keeps_recent_dirs(tmp_dir: Path) -> None:
    subtree = tmp_dir / "shell"
    _make_date_dir(subtree, days_ago=5)

    deleted = rotate_results(tmp_dir, retention_days=14, max_size_mb=500)
    assert deleted == []


def test_rotate_results_size_eviction(tmp_dir: Path) -> None:
    subtree = tmp_dir / "tool-results"
    # Two dirs that are recent (within retention), but combined > 1 MB.
    old_recent = _make_date_dir(subtree, days_ago=5, size_bytes=800_000)
    new_recent = _make_date_dir(subtree, days_ago=1, size_bytes=800_000)

    deleted = rotate_results(tmp_dir, retention_days=14, max_size_mb=1)

    # Oldest dir should be evicted; newest kept.
    assert old_recent in deleted
    assert new_recent.exists()


def test_rotate_results_spans_multiple_subtrees(tmp_dir: Path) -> None:
    tool_subtree = tmp_dir / "tool-results"
    shell_subtree = tmp_dir / "shell"
    old_tool = _make_date_dir(tool_subtree, days_ago=30)
    old_shell = _make_date_dir(shell_subtree, days_ago=30)
    recent_tool = _make_date_dir(tool_subtree, days_ago=2)

    deleted = rotate_results(tmp_dir, retention_days=14, max_size_mb=500)

    assert old_tool in deleted
    assert old_shell in deleted
    assert recent_tool.exists()


# ---------------------------------------------------------------------------
# truncation integration -- reference path is relative to workspace_root
# ---------------------------------------------------------------------------


def test_truncation_appends_relative_path(tmp_path: Path) -> None:
    """The [full output: ...] reference should be workspace-root-relative."""
    from pydantic_ai.messages import ModelRequest, ToolReturnPart

    from autopoiesis.agent.truncation import DEFAULT_MAX_BYTES, truncate_tool_results

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    big_content = "x" * (DEFAULT_MAX_BYTES + 100)
    part = ToolReturnPart(tool_name="shell", content=big_content, tool_call_id="tc1")
    msg = ModelRequest(parts=[part])

    result = truncate_tool_results([msg], workspace_root=workspace)

    assert len(result) == 1
    new_part = result[0].parts[0]
    assert isinstance(new_part, ToolReturnPart)
    assert "[full output:" in new_part.content
    # The path in the reference must NOT be absolute.
    ref_line = next(line for line in new_part.content.splitlines() if "[full output:" in line)
    ref_path_str = ref_line.split("[full output: ")[1].rstrip("]")
    assert not Path(ref_path_str).is_absolute(), f"Expected relative path, got: {ref_path_str}"
