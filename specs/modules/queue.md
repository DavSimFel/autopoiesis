# Module: queue foundation

## Purpose

Defines DBOS-backed queue primitives for non-interactive agent work so callers
can submit durable background tasks without coupling to the CLI loop.

## Status

- **Last updated:** 2026-02-15 (Issue #8)
- **Source:** `models.py`, `work_queue.py`, `chat.py`

## Components

### `models.py`

### `TaskPriority(IntEnum)`

- `CRITICAL = 1`
- `HIGH = 10`
- `NORMAL = 100`
- `LOW = 1000`
- `IDLE = 10000`

Lower numeric values indicate higher dequeue priority.

### `TaskType(StrEnum)`

- `CHAT`
- `RESEARCH`
- `CODE`
- `REVIEW`
- `MERGE`
- `CUSTOM`

### `TaskPayload(BaseModel)`

Fields:

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | `str` | `uuid4().hex[:12]` | short task id |
| `type` | `TaskType` | required | logical task category |
| `priority` | `TaskPriority` | `TaskPriority.NORMAL` | queue priority |
| `prompt` | `str` | required | single-turn agent input |
| `context` | `dict[str, Any]` | `{}` | optional caller metadata |
| `created_at` | `datetime` | `datetime.now(UTC)` | timezone-aware timestamp |
| `max_tokens` | `int | None` | `None` | optional token cap hint |

### `work_queue.py`

### `work_queue = Queue(...)`

Configuration:

- queue name: `"agent_work"`
- `priority_enabled=True`
- `concurrency=1`
- `polling_interval_sec=1.0`

Only queue instances are declared here. Workflow/step handlers stay in
`chat.py` to avoid circular imports.

## Queue Contract

- Enqueue via `work_queue.enqueue(execute_task, payload.model_dump())`.
- Set priority with `SetEnqueueOptions(priority=int(payload.priority))`.
- Background result retrieval uses DBOS handles (`handle.get_result()`).
- Payloads remain dict-based across enqueue/dequeue (`model_dump` / `model_validate`).

## Known Limitations (v1)

- SQLite can degrade queue concurrency behavior; DBOS queue semantics are
  strongest on Postgres (`SKIP LOCKED` dequeue behavior).
- No preemption inside `work_queue`: one running task occupies the slot.
- No background multi-turn conversation history: each task is single-turn.
- Interactive chat remains outside queueing and continues via `to_cli_sync()`.

## Change Log

- 2026-02-15: Created queue foundation spec covering task model, queue instance,
  enqueue contract, and SQLite limitation guidance. (Issue #8)
