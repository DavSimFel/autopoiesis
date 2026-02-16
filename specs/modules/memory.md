# Memory Module

## Overview

Persistent chat memory with semantic search via SQLite FTS5. The agent retains knowledge across sessions and can recall past decisions, preferences, and context.

## Files

| File | Responsibility |
|------|---------------|
| `memory_store.py` | SQLite schema (FTS5), save/search/combined search, workspace file search |
| `memory_tools.py` | PydanticAI tool definitions: `memory_search`, `memory_get`, `memory_save` |

## Architecture

### Two-Layer Memory

**Layer 1: Structured (SQLite)**
- `memory_entries` table with FTS5 virtual table over `summary` + `topics`
- Entries have: id, timestamp, session_id, summary, topics, raw_history_json
- Search via FTS5 MATCH with BM25 ranking

**Layer 2: Unstructured (workspace files)**
- `MEMORY.md` — curated long-term knowledge
- `memory/YYYY-MM-DD.md` — daily notes
- Searched via substring matching during `memory_search`

### Tools

- `memory_search(query, max_results=5)` — searches both layers, returns ranked results
- `memory_get(path, from_line?, lines?)` — read snippets from memory files
- `memory_save(summary, topics)` — persist a structured memory entry

### Integration

- Memory toolset wired in `chat_runtime.py` via `build_toolsets()`
- Memory store initialized at startup in `chat.py`
- System prompt instructs: search memory before answering questions about prior work

## Safety

- File paths validated with `Path.resolve().is_relative_to(workspace_root)`

## References

- Issue: #26
- Foundation for: #27 (sliding window context), #28 (subscriptions)
