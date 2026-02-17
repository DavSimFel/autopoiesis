# Memory Module

## Status

**REMOVED** as of 2026-02-17 (Issue #151).

The SQLite-based memory system (`store/memory.py`, `tools/memory_tools.py`) has been
removed in favor of the file-based knowledge system (`store/knowledge.py`).

See `specs/modules/knowledge.md` for the current memory/knowledge architecture.

## Migration

`store/knowledge_migration.py` is retained as a reference for migrating legacy
SQLite memory entries to knowledge markdown files.
