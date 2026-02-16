"""Verify default DB paths resolve to the repo-root data/ directory after move to store/."""

from pathlib import Path

from store.history import resolve_history_db_path
from store.memory import resolve_memory_db_path


def test_history_db_default_path_points_to_repo_data() -> None:
    # A non-SQLite URL triggers the default fallback path.
    result = Path(resolve_history_db_path("postgres://unused"))
    repo_root = Path(__file__).resolve().parent.parent
    expected = repo_root / "data" / "history.sqlite"
    assert result == expected


def test_memory_db_default_path_points_to_repo_data() -> None:
    result = Path(resolve_memory_db_path("postgres://unused"))
    repo_root = Path(__file__).resolve().parent.parent
    expected = repo_root / "data" / "memory.sqlite"
    assert result == expected
