"""Verify default DB paths resolve to the repo-root data/ directory after move to store/."""

from pathlib import Path


def test_history_db_default_path_points_to_repo_data() -> None:
    from store.history import _DEFAULT_HISTORY_DB_PATH  # pyright: ignore[reportPrivateUsage]

    repo_root = Path(__file__).resolve().parent.parent
    expected = repo_root / "data" / "history.sqlite"
    assert expected == _DEFAULT_HISTORY_DB_PATH


def test_memory_db_default_path_points_to_repo_data() -> None:
    from store.memory import _DEFAULT_MEMORY_DB_PATH  # pyright: ignore[reportPrivateUsage]

    repo_root = Path(__file__).resolve().parent.parent
    expected = repo_root / "data" / "memory.sqlite"
    assert expected == _DEFAULT_MEMORY_DB_PATH
