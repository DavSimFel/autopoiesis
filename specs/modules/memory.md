# Memory Module

## Status

**REMOVED** as of 2026-02-17 (Issue #151).

The SQLite-based memory system (`store/memory.py`, `tools/memory_tools.py`) has been
removed in favor of the file-based knowledge system (`store/knowledge.py`).

## Knowledge System (Issue #147)

### Frontmatter

Knowledge files support YAML frontmatter with three fields:

```yaml
---
type: fact
created: 2026-01-15T10:00:00+00:00
modified: 2026-02-01T12:00:00+00:00
---
```

- **type**: One of `fact`, `experience`, `preference`, `note`, `conversation`,
  `decision`, `contact`, `project`. Unknown types default to `note`. Skills
  can register additional types via `register_types()`.
- **created** / **modified**: ISO 8601 datetimes. Default to file mtime when
  missing.
- Files without frontmatter continue to work (backward compatible).

### Type Registry

`register_types(types: set[str])` allows skills to add custom types at startup.
`known_types()` returns all built-in + registered types.

### Filtered Search

`search_knowledge()` accepts optional `type_filter` and `since` parameters:

- `type_filter: str` - only return results from files whose frontmatter type matches.
- `since: datetime` - only return files created or modified on/after this date.

The `search` tool in `knowledge_tools.py` exposes both filters.

### Wikilink Backlink Index

`build_backlink_index(knowledge_root)` scans all markdown files for `[[target]]`
patterns and returns `dict[str, set[str]]` mapping targets to source files.
Designed to complete in <200ms for 1K files.

### Migration

`knowledge_migration.py` adds frontmatter (`type`, `created`, `modified`) to
migrated files. Existing frontmatter is preserved.

## Auto-loaded Context (unchanged)

- `knowledge/identity/*` - identity files
- `knowledge/memory/MEMORY.md` - long-term memory
- `knowledge/journal/YYYY-MM-DD.md` - today's journal

## Conversation Logging (store.conversation_log)

`store/conversation_log.py` appends per-turn conversation summaries to daily
markdown log files under `knowledge/logs/{agent_id}/YYYY-MM-DD.md`, then
re-indexes each file into the FTS5 knowledge store so T2 agents can search
conversation history.

### Public API

- `append_turn(knowledge_root, knowledge_db_path, agent_id, messages, *, timestamp)` —
  parse messages, format a markdown block, append to the daily file, and re-index.
- `rotate_logs(knowledge_root, agent_id, retention_days)` — delete log files
  older than `retention_days`; returns list of deleted paths.

### Config Integration

`AgentConfig.log_conversations: bool` (default `True`) gates logging.
`AgentConfig.conversation_log_retention_days: int` (default `30`) controls rotation.
Both fields are wired into `Runtime` and checked in `worker.run_agent_step()`.

- 2026-02-17: Paths updated for `src/autopoiesis/` layout (#152)
- 2026-02-17: Added typed frontmatter, filtered search, backlink index (#147)
- 2026-02-20: Added conversation logging for T2 reflection (#189)
