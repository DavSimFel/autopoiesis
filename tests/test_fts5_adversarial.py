"""Adversarial tests for FTS5 query sanitization in memory store."""

from __future__ import annotations

from pathlib import Path

import pytest

from memory_store import init_memory_store, save_memory, search_memory

_ADVERSARIAL_QUERIES = (
    "AND OR NOT",
    "alpha NEAR beta",
    '"phrase queries"',
    "topic:security +sqlite -fts5",
    "((nested)) && symbols!!!",
)


def _memory_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "memory.sqlite")
    init_memory_store(db_path)
    return db_path


@pytest.mark.parametrize("query", _ADVERSARIAL_QUERIES)
def test_search_memory_with_adversarial_queries_does_not_crash(
    tmp_path: Path,
    query: str,
) -> None:
    db_path = _memory_db(tmp_path)
    save_memory(db_path, "SQLite FTS5 supports phrase search", ["sqlite", "fts5"])
    save_memory(db_path, "Logical operators should be treated as plain tokens", ["security"])

    results = search_memory(db_path, query, max_results=5)
    assert isinstance(results, list)
    healthy_results = search_memory(db_path, "sqlite", max_results=5)
    assert len(healthy_results) >= 1


def test_operator_only_query_returns_empty_results(tmp_path: Path) -> None:
    db_path = _memory_db(tmp_path)
    save_memory(db_path, "SQLite FTS5 supports phrase search", ["sqlite", "fts5"])

    results = search_memory(db_path, "AND OR NOT NEAR", max_results=5)

    assert results == []
