# Module: chat

## Purpose

`chat.py` is the runtime entrypoint. It builds the agent stack, launches DBOS,
and enters the CLI chat loop. It also hosts the DBOS workflow/step functions
that execute work items from the queue.

## Status

- **Last updated:** 2026-02-15 (Issue #8)
- **Source:** `chat.py`

## File Structure

| File | Responsibility |
|------|---------------|
| `chat.py` | Startup, agent wiring, DBOS workflow/step, enqueue helpers, CLI loop |
| `models.py` | `WorkItem`, `WorkItemInput`, `WorkItemOutput`, priority/type enums |
| `work_queue.py` | Queue instance only (no functions importing from `chat.py`) |
| `streaming.py` | `StreamHandle` protocol, `PrintStreamHandle`, registry |

## Environment Variables

| Var | Required | Default | Used in | Notes |
|-----|----------|---------|---------|-------|
| `AI_PROVIDER` | No | `anthropic` | `main()` | Provider selection |
| `ANTHROPIC_API_KEY` | If anthropic | — | `build_agent()` | API key |
| `ANTHROPIC_MODEL` | No | `anthropic:claude-3-5-sonnet-latest` | `build_agent()` | Model string |
| `OPENROUTER_API_KEY` | If openrouter | — | `build_agent()` | API key |
| `OPENROUTER_MODEL` | No | `openai/gpt-4o-mini` | `build_agent()` | Model id |
| `AGENT_WORKSPACE_ROOT` | No | `data/agent-workspace` | `resolve_workspace_root()` | Resolves from `chat.py` dir |
| `DBOS_APP_NAME` | No | `pydantic_dbos_agent` | `main()` | DBOS app name |
| `DBOS_AGENT_NAME` | No | `chat` | `main()` | Agent name |
| `DBOS_SYSTEM_DATABASE_URL` | No | `sqlite:///dbostest.sqlite` | `main()` | DBOS database URL |

## Functions

### Startup

- `required_env(name)` — fail-fast env var read
- `resolve_workspace_root()` — resolve + create workspace dir
- `build_backend()` — `LocalBackend` with execute disabled
- `validate_console_deps_contract()` — structural typing guard
- `build_toolsets()` — console toolset with write approval
- `build_agent(provider, name, toolsets)` — Anthropic or OpenRouter factory

### Runtime State

- `_Runtime` dataclass holds agent + backend for the process lifetime
- `_set_runtime()` / `_get_runtime()` — set in `main()`, read by workers

### Queue Workers

- `run_agent_step(work_item_dict)` — `@DBOS.step()`. Checks for stream
  handle: if present, uses `agent.run_stream()` for real-time output;
  otherwise `agent.run_sync()`. Returns `WorkItemOutput` as dict.
- `execute_work_item(work_item_dict)` — `@DBOS.workflow()`. Delegates to
  `run_agent_step()`.

### Enqueue Helpers

- `enqueue(item)` — fire-and-forget, returns work item id
- `enqueue_and_wait(item)` — blocks on `handle.get_result()`, returns `WorkItemOutput`

### CLI

- `cli_chat_loop()` — interactive loop. Each message → `WorkItem` with
  CRITICAL priority + `PrintStreamHandle` → `enqueue_and_wait()`.
  History flows through `WorkItemInput.message_history_json`.

### Entrypoint

- `main()` — load .env → build stack → set runtime → DBOS launch → chat loop

## Invariants

- All work goes through the queue. No direct `agent.run_sync()` outside workers.
- Required env vars fail with `SystemExit`, not `KeyError`.
- `.env` loads relative to `chat.py`, not CWD.
- Workspace root resolves relative to `chat.py` when not absolute.
- Backend execute always disabled. Write approval always required.
- Console deps contract validated at startup.
- Workflow/step functions live in `chat.py` to avoid circular imports.
- Stream handles are in-process only — not durable, not serialised.

## Dependencies

- `pydantic-ai-slim[openai,anthropic,cli,dbos,mcp]>=1.59,<2`
- `pydantic-ai-backend==0.1.6`
- `python-dotenv>=1.2,<2`

## Change Log

- 2026-02-15: Unified all work through priority queue. WorkItem model with
  structured input/output. Stream handles for real-time CLI output. Removed
  `to_cli_sync()` / `DBOSAgent`. (Issue #8)
