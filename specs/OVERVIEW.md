# Autopoiesis Overview

Autopoiesis is a durable interactive CLI chat application built around a PydanticAI agent. The app is designed for local-first development with explicit environment configuration and predictable startup behaviour.

The runtime combines model-facing agent logic with durable execution so conversations can run through a DBOS-managed lifecycle. Provider selection is abstracted behind configuration so the same CLI entrypoint can target either Anthropic or OpenRouter.

## Architecture

- **PydanticAI agent** handles model orchestration, deps typing, and tool wiring.
- **DBOS durability layer** wraps agent execution and provides crash recovery.
- **Priority queue** — all work (chat, research, code, review) flows through a single DBOS queue as `WorkItem` instances.
- **Stream handles** — optional in-process handles for real-time token streaming. Convenience only; durability comes from the final output.
- **Provider abstraction** selects Anthropic or OpenRouter at startup.
- **Backend tool integration** uses `LocalBackend` and the console toolset for scoped file operations.

## Key Concepts

- **`WorkItem`** is the universal unit of work with structured `input`, `output`, and `payload`.
- **`AgentDeps`** carries runtime dependencies (currently a `LocalBackend`).
- **Console toolset** is created with `include_execute=False` and `require_write_approval=True`.
- **Provider switching** is controlled by `AI_PROVIDER` (`anthropic` or `openrouter`).
- **Fail-fast env validation** uses `required_env(...)` to raise `SystemExit` on missing keys.

## Data Flow

### All work (unified path)

1. Caller builds a `WorkItem` with `WorkItemInput(prompt=..., message_history_json=...)`
2. Optionally registers a `StreamHandle` for real-time output
3. Enqueues via `enqueue()` (fire-and-forget) or `enqueue_and_wait()` (blocking)
4. DBOS dequeues by priority
5. `execute_work_item()` → `run_agent_step()` — checks for stream handle
6. If handle present: `agent.run_stream()` with real-time output
7. If no handle: `agent.run_sync()` (background work)
8. Returns `WorkItemOutput(text=..., message_history_json=...)` as durable result

### Interactive CLI chat

Same path as above, but with `WorkItemType.CHAT`, `CRITICAL` priority,
and a `PrintStreamHandle` for stdout streaming.

## Development Workflow

- Trunk-based development with `main` as the integration branch.
- Squash merge only.
- CI requires: ruff lint, pyright strict, spec freshness check, pytest.

For workflow rationale, see `specs/decisions/001-trunk-based-workflow.md`.

## Module Index

- `chat.py`: `specs/modules/chat.md`
- Queue / WorkItem: `specs/modules/queue.md`
