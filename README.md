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
- `APPROVAL_TTL_SECONDS` sets approval expiry in seconds (default: `3600`)
- `APPROVAL_KEY_DIR` sets the approval key directory (default: `data/keys`)
- `APPROVAL_PRIVATE_KEY_PATH` sets encrypted private key path (default: `$APPROVAL_KEY_DIR/approval.key`)
- `APPROVAL_PUBLIC_KEY_PATH` sets public key path (default: `$APPROVAL_KEY_DIR/approval.pub`)
- `APPROVAL_KEYRING_PATH` sets keyring path for active/retired verification keys (default: `$APPROVAL_KEY_DIR/keyring.json`)
- `APPROVAL_KEY_PASSPHRASE` (optional) unlocks the signing key non-interactively for headless runs; prefer a secret manager because env vars can be visible to other local processes.
- `NONCE_RETENTION_PERIOD_SECONDS` sets expired envelope retention (default: `604800`)
- `APPROVAL_CLOCK_SKEW_SECONDS` sets startup skew margin for retention invariant checks (default: `60`)
- `APPROVAL_DB_PATH` (optional) overrides where deferred approval envelopes are stored. If unset, uses `data/approvals.sqlite`.
- Optional DBOS settings:
  - `DBOS_APP_NAME`
  - `DBOS_AGENT_NAME`
  - `DBOS_SYSTEM_DATABASE_URL`

## Run with uv

```bash
uv sync
uv run python chat.py
```

Rotate approval signing key (expires all pending approvals):

```bash
uv run python chat.py rotate-key
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
