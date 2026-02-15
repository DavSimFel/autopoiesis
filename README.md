# PydanticAI Durable CLI Chat

Minimal interactive CLI chat using PydanticAI + DBOS durability, with either Anthropic or OpenRouter.

## Configure

```bash
cp .env.example .env
```

Edit `.env`:

- `AI_PROVIDER=anthropic` or `AI_PROVIDER=openrouter`
- If `anthropic`: set `ANTHROPIC_API_KEY`
- If `openrouter`: set `OPENROUTER_API_KEY`
- `AGENT_WORKSPACE_ROOT` controls backend workspace location (relative paths resolve from `chat.py`)
- `SKILLS_DIR` sets the shipped skills directory path (default: `skills`, relative paths resolve from `chat.py`)
- `CUSTOM_SKILLS_DIR` sets the custom skills directory path (default: `skills`, relative paths resolve inside `AGENT_WORKSPACE_ROOT`)
- `APPROVAL_DB_PATH` (optional) overrides where deferred approval envelopes are stored. If unset, uses the SQLite file from `DBOS_SYSTEM_DATABASE_URL`.
- `APPROVAL_TTL_SECONDS` sets approval expiry in seconds (default: `3600`)
- Optional DBOS settings:
  - `DBOS_APP_NAME`
  - `DBOS_AGENT_NAME`
  - `DBOS_SYSTEM_DATABASE_URL`

## Run with uv

```bash
uv sync
uv run python chat.py
```

## Shipped Skills

Default shipped skill under `skills/`:

- `skillmaker`
  - Use `validate_skill` and `lint_skill` tools when editing skills.

Add custom skills under `<AGENT_WORKSPACE_ROOT>/skills/` (or `CUSTOM_SKILLS_DIR`).

## Run with Docker Compose

```bash
docker compose up --build
```

Notes:

- CLI is interactive (`stdin_open` + `tty` are enabled in Compose).
- DBOS sqlite state is persisted in a named volume `dbos-data` mounted at `/data`.
- Compose overrides DBOS sqlite URL to `sqlite:////data/dbostest.sqlite`.
- Backend workspace is persisted at `/data/agent-workspace` in Compose.
- Enabled backend tools: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`.
- `execute` is disabled at both toolset and backend layers.
- Writes require approval in the toolset.
- Skills are loaded from shipped + custom locations; custom skills override shipped skills when names collide.
- Container runs as non-root user `appuser`.

## VS Code

`.vscode/launch.json` runs `chat.py` and reads env vars from `.env`.
