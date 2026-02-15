# Module: chat.py

## Purpose

`chat.py` is the runtime entrypoint for the durable interactive CLI chat app. It loads configuration, builds a provider-specific PydanticAI agent with a local backend toolset, initializes DBOS, and starts the CLI loop.

## Status

- **Last updated:** 2026-02-15 (PR #2)
- **Source:** `chat.py`

## API Surface

### Environment Variables

| Env Var | Required | Default | Source in code | Description |
|---|---|---|---|---|
| `AI_PROVIDER` | No | `anthropic` | `main()` | Provider selection (`anthropic` or `openrouter`) |
| `ANTHROPIC_API_KEY` | If `AI_PROVIDER=anthropic` | - | `build_agent()` via `required_env()` | Anthropic API key |
| `ANTHROPIC_MODEL` | No | `anthropic:claude-3-5-sonnet-latest` | `build_agent()` via `os.getenv()` | Anthropic model string |
| `OPENROUTER_API_KEY` | If `AI_PROVIDER=openrouter` | - | `build_agent()` via `required_env()` | OpenRouter API key |
| `OPENROUTER_MODEL` | No | `openai/gpt-4o-mini` | `build_agent()` via `os.getenv()` | OpenRouter model string |
| `AGENT_WORKSPACE_ROOT` | No | `data/agent-workspace` | `resolve_workspace_root()` | Agent file access root (relative to `chat.py` when not absolute) |
| `DBOS_APP_NAME` | No | `pydantic_dbos_agent` | `main()` | DBOS application name |
| `DBOS_AGENT_NAME` | No | `chat` | `main()` | Agent/CLI name |
| `DBOS_SYSTEM_DATABASE_URL` | No | `sqlite:///dbostest.sqlite` | `main()` | DBOS database connection |

## Functions

### `required_env(name: str) -> str`

- Reads an env var and returns its value when present.
- Raises `SystemExit` with a clear message when missing.
- Intentionally fail-fast at startup; does not raise `KeyError`.

### `resolve_workspace_root() -> Path`

- Reads `AGENT_WORKSPACE_ROOT` with default `data/agent-workspace`.
- Resolves relative paths against `Path(__file__).resolve().parent`, not CWD.
- Creates the directory with `mkdir(parents=True, exist_ok=True)` before returning.

### `build_backend() -> LocalBackend`

- Builds `LocalBackend(root_dir=resolve_workspace_root(), enable_execute=False)`.
- Keeps shell execution disabled for the backend.

### `validate_console_deps_contract() -> None`

- Runtime compatibility check for the console toolset dependency contract.
- Verifies `AgentDeps.backend` annotation is exactly `LocalBackend`.
- Verifies `LocalBackend` exposes callable methods:
  `ls_info`, `read`, `write`, `edit`, `glob_info`, `grep_raw`.
- Exits with `SystemExit` if the structural contract is broken.

### `build_toolsets() -> list[AbstractToolset[AgentDeps]]`

- Calls `validate_console_deps_contract()` first.
- Creates one console toolset via
  `create_console_toolset(include_execute=False, require_write_approval=True)`.
- Uses an intentional `cast(...)` because the factory is typed for protocol deps,
  while `AgentDeps` satisfies that protocol structurally through `backend: LocalBackend`.

### `build_agent(provider: str, agent_name: str, toolsets: list[AbstractToolset[AgentDeps]]) -> Agent[AgentDeps, str]`

- Provider factory with explicit parameters for provider, name, and toolsets.
- Does provider branching only from the `provider` argument (selection is done in `main()`).
- `anthropic` branch:
  - requires `ANTHROPIC_API_KEY` via `required_env()`
  - uses model from `ANTHROPIC_MODEL` defaulting to `anthropic:claude-3-5-sonnet-latest`
- `openrouter` branch:
  - builds `OpenAIChatModel`
  - uses `OpenAIProvider(base_url="https://openrouter.ai/api/v1", api_key=required_env("OPENROUTER_API_KEY"))`
  - reads model from `OPENROUTER_MODEL` defaulting to `openai/gpt-4o-mini`
- Unknown provider raises `SystemExit`.

### `main() -> None`

- Startup sequence is ordered and intentional:
  1. `load_dotenv(dotenv_path=Path(__file__).with_name(".env"))`
  2. Read `AI_PROVIDER` and `DBOS_AGENT_NAME` from env
  3. `build_backend()`
  4. `build_toolsets()`
  5. `build_agent(provider, agent_name, toolsets)`
  6. `DBOS(config=dbos_config)` (defaults include SQLite URL)
  7. `DBOSAgent(agent, name=agent_name)`
  8. `DBOS.launch()`
  9. `dbos_agent.to_cli_sync(deps=AgentDeps(backend=backend))`

## Invariants & Rules

- Required env vars fail fast with `SystemExit`, not `KeyError`.
- `.env` loads from a path relative to `chat.py` (`Path(__file__).with_name(".env")`), not CWD.
- Workspace root resolves relative to `chat.py` when not absolute.
- Workspace directory is auto-created on startup.
- Backend execute is always disabled (`enable_execute=False`).
- Write approval is always required (`require_write_approval=True`).
- Console deps contract is validated at startup (`validate_console_deps_contract()`).
- `build_toolsets()` uses intentional `cast()` because `AgentDeps` satisfies the console deps protocol structurally via `backend: LocalBackend`.
- DBOS defaults to SQLite (`sqlite:///dbostest.sqlite`), which is appropriate for development and typically replaced in production.

## Dependencies

- `pydantic-ai-slim[openai,anthropic,cli,dbos,mcp]>=1.59,<2` - core agent framework with provider, CLI, and DBOS extras.
- `pydantic-ai-backend==0.1.6` - `LocalBackend` and console toolset integration.
- `python-dotenv>=1.2,<2` - `.env` loading.

Notes:
- `dbos` is consumed via the `dbos` extra on `pydantic-ai-slim`, not as a direct top-level dependency entry.
- The `mcp` extra is present in `pyproject.toml` but not currently used directly in `chat.py`.

## Change Log

- 2026-02-15: Added living module spec synced to current `chat.py` implementation, including env vars, startup order, and structural typing contract details. (PR #2)

