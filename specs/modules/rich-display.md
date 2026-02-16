# Module: rich-display

## Purpose
Rich-powered live terminal UI for streamed assistant output, tool calls,
and reasoning. Each activity gets its own display channel rendered as a
branch in a Rich tree.

## Status
- **Last updated:** 2026-02-16 (Issue #25)
- **Source:** `rich_display.py`, `streaming.py`

## Key Concepts

- **Display channel** — one logical activity (response, tool call, thinking).
  Each has an id, label, content buffer, status, and optional summary.
- **Channel lifecycle** — `running` → `done` | `error`. Running channels
  show a live tail of recent output. Completed channels show a one-line
  summary (never hidden).
- **Pinned channels** — always show full content (e.g. assistant response).
  Never auto-summarized.
- **Non-TTY fallback** — `RichStreamHandle` falls back to `PrintStreamHandle`
  when stdout is not a terminal.
- **Pause/resume** — Live rendering pauses during approval prompts so
  `input()` works correctly, then resumes.
- **Plain-text final output** — on `close()`, pinned channel content is
  printed as plain text for scrollback and log file compatibility.

## Architecture

`RichDisplayManager` owns a `rich.live.Live` instance with a tree render
callback at 4fps. Channel state is tracked in `DisplayChannel` dataclasses.
Thread-safe via `threading.RLock`.

`RichStreamHandle` implements `StreamHandle` + `ToolAwareStreamHandle`
protocols. Routes:
- Assistant text → pinned "Response" channel
- Tool calls → per-call channels with args (running) → summary (done)
- Thinking → dedicated channel with live tail → collapsed on completion

`chat_worker.py` forwards PydanticAI `AgentStreamEvent`s:
- `FunctionToolCallEvent` → `start_tool_call`
- `FunctionToolResultEvent` → `finish_tool_call`
- `PartStartEvent(ThinkingPart)` → `start_thinking`
- `PartDeltaEvent(ThinkingPartDelta)` → `update_thinking`

## API Surface

### RichDisplayManager
- `create_channel(id, label, *, pinned=False)`
- `update_channel(id, content)`
- `complete_channel(id, status, summary=None)`
- `close()` — stop Live, print final plain text
- `pause()` / `resume()` — for interactive prompts

### RichStreamHandle
- `write(chunk)` / `close()` — StreamHandle protocol
- `start_tool_call` / `finish_tool_call` — tool lifecycle
- `start_thinking` / `update_thinking` / `finish_thinking` — reasoning
- `pause_display` / `resume_display` — approval flow

## Invariants

- Assistant response channel is pinned — never summarized or hidden.
- Completed tool channels show a one-line summary, not just an icon.
- Live rendering stops cleanly before any `input()` call.
- Non-TTY outputs fall back to plain print — no Rich dependency at runtime.
- Final plain-text output ensures scrollback/log compatibility.
- Refresh rate is 4fps (not 12) to avoid unnecessary CPU.
- `transient=True` on Live so intermediate renders don't pollute scrollback.

## Dependencies

- External: `rich>=13.0`
- Internal: `chat_cli.py`, `chat_worker.py`

## Change Log

- 2026-02-16: Initial implementation with pinned response channel,
  per-tool summary channels, thinking/reasoning stream, approval
  pause/resume, non-TTY fallback, and plain-text final output.
  (Issue #25)

- 2026-02-16: Exposed test hooks in `rich_display.py` to eliminate `# pyright: ignore`
  suppressions in test files. (Issue #77)
- 2026-02-16: Code smell cleanup — improved error messages, removed defensive checks,
  narrowed exception handling, cached regex. (Issue #89)
