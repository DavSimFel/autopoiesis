# AGENTS.md

## Project Overview
Durable interactive CLI chat built with PydanticAI + DBOS, with provider switch between Anthropic and OpenRouter.

- Runtime: Python 3.12+
- Package manager: `uv` only
- Entry point: `chat.py`
- Backend integration: `pydantic-ai-backend==0.1.6` via `pydantic_ai_backends`

## Setup Commands

```bash
cp .env.example .env
uv sync
```

## Run Commands

```bash
uv run python chat.py
docker compose up --build
```

## Validation Commands

```bash
python3 -m py_compile chat.py
docker compose config
```

Notes:
- There are no automated tests in this repo yet.
- Do not claim tests passed.

## Project Structure

```text
chat.py               # Provider selection, env loading, backend toolset wiring, DBOS launch, interactive CLI
pyproject.toml        # Dependency source of truth
uv.lock               # Locked dependency graph
docker-compose.yml    # Interactive container runtime + DBOS volume
Dockerfile            # uv-based image, non-root runtime
.env.example          # Required config template
.vscode/launch.json   # Local debug config using .env
```

## Code Conventions

- Keep provider values explicit: `AI_PROVIDER=openrouter` or `AI_PROVIDER=anthropic`.
- Validate required keys with `required_env(...)` before use.
- Guard optional/runtime imports with fail-fast `SystemExit` messages that recommend `uv sync`.
- For OpenRouter use `OpenAIChatModel` + `OpenAIProvider(base_url="https://openrouter.ai/api/v1")`.
- For Anthropic use model strings with `anthropic:` prefix.
- Load env from repo-local file only:
  - `load_dotenv(dotenv_path=Path(__file__).with_name(".env"))`
- Backend wiring pattern:
  - Define `AgentDeps` with `backend: LocalBackend`.
  - Build backend with `LocalBackend(root_dir=..., enable_execute=False)`.
  - Build toolset with `create_console_toolset(include_execute=False, require_write_approval=True)`.
  - Pass `deps_type=AgentDeps` and `toolsets=[...]` when constructing `Agent`.
  - Pass runtime deps to CLI via `dbos_agent.to_cli_sync(deps=AgentDeps(backend=backend))`.
- Resolve `AGENT_WORKSPACE_ROOT` relative to `chat.py` when env value is not absolute.
- Keep startup order:
  1. load env
  2. validate/build agent
  3. configure DBOS
  4. launch DBOS
  5. start CLI

## Security Rules

- Never commit secrets or tokens.
- `.env`, sqlite artifacts, caches, and virtualenv must stay ignored.
- Never log API keys or full auth headers.

## Change Rules

- Keep edits minimal and scoped to the request.
- Do not add dependencies without explicit user approval.
- Update `README.md` and `.env.example` whenever env vars or run commands change.
