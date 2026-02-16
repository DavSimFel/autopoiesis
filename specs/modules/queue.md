# Module: work queue

## Purpose

DBOS-backed priority queue through which ALL agent work flows — interactive
chat, background research, code generation, reviews. One queue, one path.

## Status

- **Last updated:** 2026-02-16 (Issue #19, #21)
- **Source:** `models.py`, `work_queue.py`, `streaming.py`, `chat_worker.py`, `chat_cli.py`

## Core Concept: WorkItem

A `WorkItem` is the universal unit of work. It has:

- **input** (`WorkItemInput`): prompt + optional message history + optional deferred approvals
- **output** (`WorkItemOutput`): agent response + updated history (filled after execution)
- **payload** (`dict[str, Any]`): arbitrary caller metadata

Stream handles can be registered for a WorkItem to receive tokens in real
time. Handles are in-process only (not serialised, not durable). Durability
comes from the final `WorkItemOutput` persisted after completion.

## Components

### `models.py`

#### `WorkItemPriority(IntEnum)`

| Level | Value | Use case |
|-------|-------|----------|
| CRITICAL | 1 | Interactive chat (user waiting) |
| HIGH | 10 | PR reviews, blocking work |
| NORMAL | 100 | Code generation |
| LOW | 1000 | Research, analysis |
| IDLE | 10000 | Housekeeping |

#### `WorkItemType(StrEnum)`

`CHAT`, `RESEARCH`, `CODE`, `REVIEW`, `MERGE`, `CUSTOM`

#### `WorkItemInput(BaseModel)`

| Field | Type | Notes |
|-------|------|-------|
| `prompt` | `str \| None` | Agent input text (None when resuming approval loop) |
| `message_history_json` | `str \| None` | Serialised PydanticAI message history |
| `deferred_tool_results_json` | `str \| None` | Serialized deferred approval submission (`nonce` + per-call decisions) |
| `approval_context_id` | `str \| None` | Stable id across re-enqueued approval loop items |

#### `WorkItemOutput(BaseModel)`

| Field | Type | Notes |
|-------|------|-------|
| `text` | `str \| None` | Agent response (None when requesting approval) |
| `message_history_json` | `str \| None` | Updated history for next turn |
| `deferred_tool_requests_json` | `str \| None` | Serialized deferred approval requests (`nonce` + plan-hash prefix + tool calls) |

#### `WorkItem(BaseModel)`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id` | `str` | `uuid4().hex` | Unique id |
| `type` | `WorkItemType` | required | Intent category |
| `priority` | `WorkItemPriority` | `NORMAL` | Queue priority |
| `input` | `WorkItemInput` | required | Structured inputs |
| `output` | `WorkItemOutput \| None` | `None` | Filled after execution |
| `payload` | `dict[str, Any]` | `{}` | Arbitrary metadata |
| `created_at` | `datetime` | `now(UTC)` | Timezone-aware |

### `work_queue.py`

Single queue instance — no functions, no imports from `chat.py`:

- Queue name: `"agent_work"`
- `priority_enabled=True`
- `concurrency=1`
- `polling_interval_sec=1.0`

### `streaming.py`

In-process stream handle registry for real-time output.

- `StreamHandle` protocol: `write(chunk)` + `close()`
- `PrintStreamHandle`: prints chunks to stdout
- `register_stream(id, handle)`: register before enqueue
- `take_stream(id)`: worker pops handle, streams to it

**Not durable.** Handles live in-process only. If the process crashes
mid-stream, DBOS replays the workflow — the handle is gone, so the worker
falls back to non-streaming `run_sync()`. The durable output is the same
either way.

## Queue Contract

1. Build a `WorkItem` with structured `input`
2. Optionally `register_stream(item.id, handle)` for real-time output
3. `enqueue(item)` for fire-and-forget, or `enqueue_and_wait(item)` to block
4. Worker calls `execute_work_item()` → `run_agent_step()`
5. Worker checks for stream handle: if present → `run_stream_sync()`, else → `run_sync()`
6. Returns `WorkItemOutput` as durable result

## History Checkpointing

History checkpointing adds per-round persistence for in-flight work item
execution so DBOS replay can resume with minimal repeated model work.

- **How it works:** Agent `history_processors` persist serialized message
  history to SQLite after each model round during `run_sync()` / `run_stream_sync()`.
- **Recovery flow:** On `run_agent_step()` start, worker loads checkpoint by
  `work_item_id` and prefers it over `WorkItemInput.message_history_json`.
  After successful completion, checkpoint row is cleared.
- **Version handling:** Checkpoint rows with a mismatched
  `checkpoint_version` are treated as stale and ignored. Execution falls back
  to `WorkItemInput.message_history_json`.
- **Storage:** Checkpoints live in `agent_history_checkpoints` in SQLite.
  For SQLite DBOS URLs, the file is colocated with DBOS system DB using
  `*_history.sqlite`; for Postgres DBOS URLs, fallback path is
  `data/history.sqlite`.
- **Limitations:** A crash can still replay at most one model call between the
  last persisted round and failure boundary.

## Known Limitations (v1)

- **SQLite degrades queue concurrency** — `SKIP LOCKED` is Postgres-native.
  SQLite dev mode may serialise dequeue. Document Postgres for production.
- **No preemption** — a running work item occupies the slot until done.
- **Stream handles are single-process** — no cross-process streaming.
- **`concurrency=1`** — one work item at a time. Chat with CRITICAL priority
  jumps the queue but still waits for any in-flight item to finish.

## Change Log

- 2026-02-16: Checkpoint loading now validates `checkpoint_version` and falls
  back to input history on mismatch. Active checkpoint state in workers is
  context-local (`ContextVar`) instead of module-global mutable state.
  (Issue #21, PR #23)
- 2026-02-16: Moved queue worker/execution helpers from `chat.py` into
  `chat_worker.py`; queue contract and transport schema unchanged.
  (Issue #19, PR #20)
- 2026-02-15: Created. WorkItem model, stream handles, unified queue path. (Issue #8)
- 2026-02-15: Added history checkpoint persistence + crash recovery resume flow. (Issue #21)
- 2026-02-15: Added deferred-approval transport fields to WorkItem input/output
  and stable `approval_context_id` for multi-step approval verification. (Issue #19)
- 2026-02-15: Deferred approvals now use signed envelope-backed verification:
  CLI signs decisions before re-enqueue; worker verifies signature/context/bijection
  before atomic nonce consumption. Transport schema remains `nonce + decisions`.
  (Issue #19)

- 2026-02-16: Code smell cleanup — improved error messages, removed defensive checks,
  narrowed exception handling, cached regex. (Issue #89)

### Changelog
- 2026-02-16: Modules moved into subdirectories (`agent/`, `approval/`, `display/`, `infra/`, `store/`, `tools/`) as part of subdirectory restructuring (#119)
- 2026-02-16: Added Dependencies/Wired-in docstring headers (#121)
