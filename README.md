# Autopoiesis

A **durable CLI agent** built on [PydanticAI](https://ai.pydantic.dev/) + [DBOS](https://docs.dbos.dev/) with multi-agent coordination, cryptographic approval gates, and a file-first knowledge system.

## What It Does

- Interactive CLI chat agent with streaming Rich terminal UI
- **Durable execution** — DBOS priority queue survives crashes, retries automatically
- **Cryptographic approval** — Ed25519-signed envelopes gate shell/file operations
- **Multi-agent capable** — WorkItem queue supports T1 (human) → T2 (planner) → T3 (worker) tiers
- **File-first knowledge** — markdown files, git versioning, FTS5 search
- **Skill system** — drop a `SKILL.md` file, agent discovers it at startup

## Quick Start

```bash
git clone https://github.com/DavSimFel/autopoiesis.git
cd autopoiesis

uv sync                       # install deps
cp .env.example .env          # configure API keys

uv run pytest                 # run all tests
uv run pytest tests/integration/  # integration tests only
uv run python chat.py         # start the agent
```

## Verify

```bash
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run pyright                # type checking
uv run pytest                 # tests
```

All four must pass before pushing.

## Configuration

Edit `.env`:

| Variable | Purpose |
|----------|---------|
| `AI_PROVIDER` | `anthropic` or `openrouter` |
| `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` | Provider credentials |
| `AGENT_WORKSPACE_ROOT` | Agent workspace location |
| `SKILLS_DIR` | Shipped skills directory (default: `skills`) |
| `CUSTOM_SKILLS_DIR` | Custom skills inside workspace (default: `skills`) |

See `.env.example` for the full list including approval and DBOS settings.

## Docker

```bash
docker compose up --build
```

DBOS state persists in a `dbos-data` volume. Container runs as non-root `appuser`.

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — system design, tool inventory, agent tiers
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — developer workflow, CI, specs
- **[docs/testing.md](docs/testing.md)** — complete testing guide
- **[specs/](specs/)** — module specifications (the source of truth)

## License

See [LICENSE](LICENSE).
