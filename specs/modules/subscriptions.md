# Subscriptions Module

## Overview

Reactive context injection via file and memory subscriptions. The agent subscribes once to a resource; before each turn, subscribed content is automatically materialized and injected into the conversation context.

## Files

| File | Responsibility |
|------|---------------|
| `subscriptions.py` | `Subscription` dataclass, `SubscriptionRegistry` (SQLite-backed CRUD), content hashing, truncation |
| `subscription_tools.py` | PydanticAI tool definitions: `subscribe_file`, `subscribe_memory`, `unsubscribe`, `unsubscribe_all`, `list_subscriptions` |
| `subscription_processor.py` | History processor that materializes subscriptions into `ModelRequest` messages before each turn |

## Architecture

### Subscription Model

A `Subscription` is a frozen dataclass referencing a resource:

- **`kind`**: `file` | `lines` | `memory`
- **`target`**: file path (file/lines) or query string (memory)
- **`line_range`**: optional `(start, end)` for line-scoped file subscriptions
- **`pattern`**: optional regex filter for file lines
- **`content_hash`**: SHA-256 prefix of last materialized content

### Registry

`SubscriptionRegistry` persists subscriptions in SQLite with WAL journaling. Keyed by `(session_id, target, kind)` with UNIQUE constraint for upsert semantics. Limits: max 10 per session, auto-expire after 24h.

### Materialization (History Processor)

`materialize_subscriptions` runs in the history processor chain:

1. Strips old materialization messages (identified by `metadata.materialized_subscriptions`)
2. Resolves all active subscriptions to current content
3. Inserts a `ModelRequest` with `UserPromptPart`s right before the final user message

This ensures the LLM always sees fresh subscription content at the optimal position (end of context, just before the user's latest message).

### Integration

The processor chain order in `chat.py`:
1. `truncate_tool_results` — cap oversized tool outputs
2. `compact_history` — compress older messages
3. `materialize_subscriptions` — inject subscription content
4. `checkpoint_history_processor` — persist raw history (pre-materialization excluded from checkpoints)

### Limits

- Max 10 active subscriptions per session
- Each materialized content capped at 2000 characters (truncated with notice)
- File subscriptions constrained to workspace root (path traversal blocked)
- Auto-expire after 24 hours without renewal

## Tools

| Tool | Purpose |
|------|---------|
| `subscribe_file(path, lines?, pattern?)` | Subscribe to a workspace file |
| `subscribe_memory(query)` | Subscribe to a memory FTS5 search query |
| `unsubscribe(subscription_id)` | Remove a subscription by id |
| `unsubscribe_all()` | Clear all subscriptions |
| `list_subscriptions()` | Show active subscriptions |

## Dependencies

- `memory_store.py` — for memory subscription resolution (FTS5 search)
- PydanticAI `HistoryProcessor` — for message injection
- PydanticAI `ModelRequest.metadata` — for tagging materialization messages

- 2026-02-16: Replaced inline WAL pragma with shared `open_db()` from `db.py`. (Issue #84)
