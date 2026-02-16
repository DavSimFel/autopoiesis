# Module: context

## Purpose
Sliding-window context management and tool-result truncation to keep
conversation history within model context limits.

## Status
- **Last updated:** 2026-02-16 (Issue #27)
- **Source:** `context_manager.py`, `tool_result_truncation.py`

## Key Concepts
- **Token estimation** — character-based heuristic (~4 chars/token)
- **Compaction** — when history exceeds threshold, older turns are summarized into one message
- **Tool result truncation** — large tool outputs are saved to disk and replaced with truncated previews

## Architecture
Both modules are wired as `history_processors` in the PydanticAI agent
(via `chat.py`). They run in order: truncation → compaction → checkpoint.

## API Surface

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `CONTEXT_WINDOW_TOKENS` | `100000` | Max context window in tokens |
| `COMPACTION_THRESHOLD` | `0.7` | Fraction of window that triggers compaction |

### Functions

#### `context_manager.py`
- `estimate_tokens(text: str) -> int` — character-based token estimate
- `compact_history(messages, max_tokens?, keep_recent=10) -> list[ModelMessage]` — compact older turns if over threshold

#### `tool_result_truncation.py`
- `truncate_tool_results(messages, workspace_root, max_chars=5000) -> list[ModelMessage]` — truncate large tool results, save full output to `.tmp/tool-results/<call-id>.log`

## Invariants & Rules
- Recent messages (last `keep_recent`) are never compacted
- Full tool output is always preserved on disk before truncation
- Compaction only triggers above the configured threshold

## Dependencies
- **External:** `pydantic-ai` (message types)
- **Internal:** wired via `chat.py` history_processors

## Change Log
- 2026-02-16: Initial implementation — sliding window + truncation (Issue #27)
