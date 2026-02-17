# Memory Module

## Status

**REMOVED** as of 2026-02-17 (Issue #151).

The SQLite-based memory system (`store/memory.py`, `tools/memory_tools.py`) has been
removed in favor of the file-based knowledge system (`store/knowledge.py`).

<<<<<<< HEAD
See `specs/modules/knowledge.md` for the current memory/knowledge architecture.
=======
| File | Responsibility |
|------|---------------|
| `src/autopoiesis/store/memory.py` | SQLite schema (FTS5), save/search/combined search, workspace file search |
| `memory_tools.py` | PydanticAI tool definitions: `memory_search`, `memory_get`, `memory_save` |
>>>>>>> b8ed9c3 (refactor: move source to src/autopoiesis/ layout (closes #152))

## Migration

<<<<<<< HEAD
`store/knowledge_migration.py` is retained as a reference for migrating legacy
SQLite memory entries to knowledge markdown files.
=======
### Two-Layer Memory

**Layer 1: Structured (SQLite)**
- `memory_entries` table with FTS5 virtual table over `summary` + `topics`
- Entries have: id, timestamp, session_id, summary, topics, raw_history_json
- Search via FTS5 MATCH with BM25 ranking
- Connections use explicit close semantics (`contextlib.closing` + transaction context)
- Each SQLite connection enables `PRAGMA journal_mode=WAL`

**Layer 2: Unstructured (workspace files)**
- `MEMORY.md` — curated long-term knowledge
- `memory/YYYY-MM-DD.md` — daily notes
- Searched via substring matching during `memory_search`

### Tools

- `memory_search(query, max_results=5)` — searches both layers, returns ranked results
- `memory_get(path, from_line?, lines?)` — read snippets from memory files
- `memory_save(summary, topics)` — persist a structured memory entry

### Integration

- Memory toolset wired in `agent/runtime.py` via `build_toolsets()`
- Memory store initialized at startup in `src/autopoiesis/cli.py`
- System prompt instructs: search memory before answering questions about prior work

## Observability

- All memory tools carry `metadata={"category": "memory"}` for toolset-level observability.

## Safety

- File paths validated with `Path.resolve().is_relative_to(workspace_root)`

## References

- Issue: #26
- Reliability hardening: #44
- Foundation for: #27 (sliding window context), #28 (subscriptions)

- 2026-02-16: Extracted shared `db.py` connection factory (`open_db()`); replaced inline
  WAL pragma in `src/autopoiesis/store/history.py` and `src/autopoiesis/store/memory.py`. (Issue #84)
- 2026-02-16: FTS5 sanitizer bugfix — `_sanitize_fts_query` now strips FTS5 keywords
  (AND, OR, NOT, NEAR) from user input to prevent them from altering query semantics.
  (Issue #88, PR #111)

### Changelog
- 2026-02-16: Modules moved into subdirectories (`agent/`, `approval/`, `display/`, `infra/`, `store/`, `tools/`) as part of subdirectory restructuring (#119)
- 2026-02-16: Added Dependencies/Wired-in docstring headers as part of #121 documentation update
- 2026-02-16: Knowledge system integration — startup indexing, knowledge tools wiring, memory store deprecated (#130)
>>>>>>> b8ed9c3 (refactor: move source to src/autopoiesis/ layout (closes #152))
