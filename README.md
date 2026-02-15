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
- Optional DBOS settings:
  - `DBOS_APP_NAME`
  - `DBOS_AGENT_NAME`
  - `DBOS_SYSTEM_DATABASE_URL`

## Run with uv

```bash
uv sync
uv run python chat.py
```

## Run with Docker Compose

```bash
docker compose up --build
```

Notes:

- CLI is interactive (`stdin_open` + `tty` are enabled in Compose).
- DBOS sqlite state is persisted in a named volume `dbos-data` mounted at `/data`.
- Compose overrides DBOS sqlite URL to `sqlite:////data/dbostest.sqlite`.
- Container runs as non-root user `appuser`.

## VS Code

`.vscode/launch.json` runs `chat.py` and reads env vars from `.env`.
