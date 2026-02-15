# Module: chat.py

## Purpose

`chat.py` is the runtime entrypoint for durable interactive CLI chat and the host
module for DBOS background task execution handlers.

Interactive chat behavior remains on `DBOSAgent(...).to_cli_sync(...)`.
Background work executes through the DBOS `work_queue` by enqueuing
`execute_task(payload_dict)` payloads.

## Status

- **Last updated:** 2026-02-15 (Issue #8)
- **Source:** `chat.py`

## File Structure

- `chat.py`: app startup, provider selection, backend/toolset wiring, DBOS launch,
  interactive CLI start, queue workflow/step handlers, enqueue helpers.
- `models.py`: queue payload models and enums.
- `work_queue.py`: queue instance declarations only.

## API Surface

### Environment Variables

| Env Var | Required | Default | Source in code | Description |
|---|---|---|---|---|
| `AI_PROVIDER` | No | `anthropic` | `main()` | Provider selection (`anthropic` or `openrouter`) |
| `ANTHROPIC_API_KEY` | If `AI_PROVIDER=anthropic` | - | `build_agent()` via `required_env()` | Anthropic API key |
| `ANTHROPIC_MODEL` | No | `anthropic:claude-3-5-sonnet-latest` | `build_agent()` | Anthropic model string with required `anthropic:` prefix |
| `OPENROUTER_API_KEY` | If `AI_PROVIDER=openrouter` | - | `build_agent()` via `required_env()` | OpenRouter API key |
| `OPENROUTER_MODEL` | No | `openai/gpt-4o-mini` | `build_agent()` | OpenRouter model id |
| `AGENT_WORKSPACE_ROOT` | No | `data/agent-workspace` | `resolve_workspace_root()` | Agent workspace root (relative values resolve from `chat.py`) |
| `DBOS_APP_NAME` | No | `pydantic_dbos_agent` | `main()` | DBOS application name |
| `DBOS_AGENT_NAME` | No | `chat` | `main()` | Durable CLI agent name |
| `DBOS_SYSTEM_DATABASE_URL` | No | `sqlite:///dbostest.sqlite` | `main()` | DBOS system database connection URL |

### Runtime Setup Functions

### `required_env(name: str) -> str`

- Returns a required env var value.
- Raises `SystemExit` when missing.

### `resolve_workspace_root() -> Path`

- Resolves `AGENT_WORKSPACE_ROOT`.
- Uses `chat.py` directory for relative paths.
- Creates the directory if missing.

### `build_backend() -> LocalBackend`

- Builds `LocalBackend(root_dir=..., enable_execute=False)`.

### `build_toolsets() -> list[AbstractToolset[AgentDeps]]`

- Validates backend/toolset contract first.
- Creates one console toolset with:
  - `include_execute=False`
  - `require_write_approval=True`

### `build_agent(...) -> Agent[AgentDeps, str]`

- Creates an Anthropic or OpenRouter-backed agent from explicit provider input.
- Enforces required provider API keys with `required_env(...)`.

### Queue Execution Functions

### `run_agent_step(prompt: str) -> str`

- DBOS step (`@DBOS.step()`).
- Executes one agent turn using module-level runtime `agent` + `backend`.
- Returns text output for checkpoint-able background processing.

### `execute_task(payload_dict: dict[str, Any]) -> str`

- DBOS workflow (`@DBOS.workflow()`).
- Validates queue payload with `TaskPayload.model_validate(payload_dict)`.
- Calls `run_agent_step(payload.prompt)`.

### `enqueue_task(task_type: TaskType, prompt: str, **kwargs: Any) -> str`

- Creates a `TaskPayload`.
- Enqueues to `work_queue` with `SetEnqueueOptions(priority=payload.priority)`.
- Passes `payload.model_dump()` (dict, not serialized JSON string).
- Returns generated task id.

### `enqueue_task_and_wait(task_type: TaskType, prompt: str, **kwargs: Any) -> str`

- Enqueues with queue priority and immediately calls `handle.get_result()`.
- Validates result is `str` and returns it.

### `main() -> None`

Ordered startup sequence:

1. `load_dotenv(dotenv_path=Path(__file__).with_name(".env"))`
2. Build backend, toolsets, and provider agent
3. Set module-level runtime state for queue handlers
4. Configure DBOS (`DBOS(config=dbos_config)`)
5. Launch DBOS (`DBOS.launch()`)
6. Start interactive CLI via `dbos_agent.to_cli_sync(deps=AgentDeps(backend=backend))`

## Invariants & Rules

- Interactive CLI chat remains on `to_cli_sync()` (no queue regression in v1).
- Background tasks must route through `work_queue.enqueue(execute_task, payload_dict)`.
- `execute_task` and `run_agent_step` remain in `chat.py` to avoid circular imports.
- Queue payloads are dict-based (`model_dump` / `model_validate`) with no double serialization.
- Module-level runtime state is initialized in `main()` before `DBOS.launch()`.

## Dependencies

- `pydantic-ai-slim[openai,anthropic,cli,dbos,mcp]>=1.59,<2`
- `pydantic-ai-backend==0.1.6`
- `python-dotenv>=1.2,<2`

## Change Log

- 2026-02-15: Added background queue execution workflow/step wiring while preserving `to_cli_sync()` interactive chat path. Added enqueue helpers and module split references. (Issue #8)
