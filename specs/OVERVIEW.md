# Autopoiesis Overview

Autopoiesis is a durable interactive CLI chat application built around a PydanticAI agent. The app is designed for local-first development with explicit environment configuration and predictable startup behavior.

The runtime combines model-facing agent logic with durable execution so conversations can run through a DBOS-managed lifecycle. Provider selection is abstracted behind configuration so the same CLI entrypoint can target either Anthropic or OpenRouter.

## Architecture

- **PydanticAI agent** handles model orchestration, deps typing, and tool wiring.
- **DBOS durability layer** wraps agent execution and provides launch/runtime lifecycle management.
- **Provider abstraction** selects Anthropic or OpenRouter at startup without changing call sites.
- **Backend tool integration** uses `LocalBackend` and the console toolset for file operations inside a scoped workspace.

## Key Concepts

- **`AgentDeps`** carries runtime dependencies for each turn; currently a `LocalBackend`.
- **`LocalBackend`** provides file operations with shell execution disabled.
- **Console toolset** is created with `include_execute=False` and `require_write_approval=True`.
- **Provider switching** is controlled by `AI_PROVIDER` (`anthropic` or `openrouter`).
- **Fail-fast env validation** uses `required_env(...)` to raise `SystemExit` on missing required keys.

## Data Flow

1. `.env`
2. `load_dotenv(dotenv_path=Path(__file__).with_name(".env"))`
3. `os.getenv(...)` reads env vars
4. `build_backend()` / `build_toolsets()` / `build_agent(...)`
5. `DBOS(config=dbos_config)`
6. `DBOS.launch()`
7. `dbos_agent.to_cli_sync(deps=AgentDeps(backend=backend))`

## Development Workflow

- Trunk-based development with `main` as the integration branch.
- Short-lived branches (or worktrees) for focused changes.
- Open PRs against `main`.
- Squash merge to keep history linear and reduce merge noise.

For workflow rationale, see `specs/decisions/001-trunk-based-workflow.md`.

## Module Index

- `chat.py`: `specs/modules/chat.md`

