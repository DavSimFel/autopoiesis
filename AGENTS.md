# AGENTS.md

## Project
Durable interactive CLI chat built with PydanticAI + DBOS, with provider switch
between Anthropic and OpenRouter. Python 3.12+, `uv` only.

- Entry point: `chat.py`
- Backend integration: `pydantic-ai-backend==0.1.6` via `pydantic_ai_backends`

## Commands
- Setup env: `cp .env.example .env`
- Install: `uv sync`
- Run: `uv run python chat.py`
- Docker: `docker compose up --build` / `docker compose config`
- Lint: `uv run ruff check path/to/file.py`
- Lint all: `uv run ruff check .`
- Format: `uv run ruff format path/to/file.py`
- Typecheck: `uv run pyright path/to/file.py`
- Test: `uv run pytest`
- Compile check: `python3 -m py_compile chat.py`
- Automated tests exist — ensure they pass before claiming completion.

## Architecture
Entry point: `chat.py` (single file)

Project files:
- `chat.py`: provider selection, env loading, backend toolset wiring, DBOS launch, interactive CLI
- `pyproject.toml`: dependency source of truth
- `uv.lock`: locked dependency graph
- `docker-compose.yml`: interactive container runtime + DBOS volume
- `Dockerfile`: uv-based image, non-root runtime
- `.env.example`: required config template
- `.vscode/launch.json`: local debug config using `.env`

Backend wiring pattern (do not deviate):
- `AgentDeps` dataclass with `backend: LocalBackend`
- `LocalBackend(root_dir=..., enable_execute=False)`
- `create_console_toolset(include_execute=False, require_write_approval=True)`
- `Agent(model, deps_type=AgentDeps, toolsets=[...])`
- `dbos_agent.to_cli_sync(deps=AgentDeps(backend=backend))`

Runtime conventions:
- Keep provider values explicit: `AI_PROVIDER=openrouter` or `AI_PROVIDER=anthropic`
- Validate required keys with `required_env(...)` before use
- Guard optional/runtime imports with fail-fast `SystemExit` messages recommending `uv sync`
- `AI_PROVIDER=anthropic`: use model strings with `anthropic:` prefix
- `AI_PROVIDER=openrouter`: use `OpenAIChatModel` + `OpenAIProvider(base_url="https://openrouter.ai/api/v1")`
- Resolve `AGENT_WORKSPACE_ROOT` relative to `chat.py` when env value is not absolute

Startup order (sequence matters):
1. `load_dotenv(dotenv_path=Path(__file__).with_name(".env"))`
2. Validate/build backend + toolsets + agent
3. Configure DBOS
4. `DBOS.launch()`
5. Start CLI

## Code Style
- Strict typing (`pyright strict`), ruff enforced
- Max file: 300 lines. Max function: 50 lines. Max complexity: 10.
- No `# noqa`, no Pyright ignore directives, and no type-ignore directives — fix the code
- Comments explain WHY, never WHAT. No commented-out code.
- No TODOs without issue numbers: `# TODO(#42): description`
- One logical change per commit
- Keep edits minimal and scoped to the request
- Do not add dependencies without explicit user approval
- Update `README.md` and `.env.example` whenever env vars or run commands change

## Spec Rules (MANDATORY)
- Every PR that changes behavior MUST update `specs/modules/`
- New modules → new spec from `specs/_template.md`
- Architectural decisions → ADR in `specs/decisions/`
- Update `specs/OVERVIEW.md` if system-level architecture changes
- Add changelog entry with date and PR/issue number

## Git Workflow
See [WORKFLOW.md](WORKFLOW.md) for the full issue pipeline (creation → review → implement → PR review → merge).

- Branch from `main`: `{type}/issue-{number}-{slug}`
- Types: feat, fix, chore, refactor, docs
- Squash merge to `main` only — no direct pushes
- Delete branch after merge
- Commit format: `feat(chat): add provider caching (#42)`

## Post-Merge Smoke Test (MANDATORY)
After every merge to `main`, run a smoke test before declaring success:
1. `git pull origin main`
2. `ruff check . && ruff format --check .`
3. `pyright`
4. `python -m pytest` (full suite)
5. If ANY check fails → fix immediately on a hotfix branch, do NOT leave main broken
Never merge the next PR until main is green.

## Security
- Never commit secrets or tokens
- `.env`, sqlite artifacts, caches, virtualenv must stay in `.gitignore`
- Never log API keys or full auth headers

## Anti-Patterns (instant PR rejection)
1. Lint/type suppressions (`# noqa`, any Pyright ignore directive, any type-ignore directive)
2. Weakening lint rules to pass CI
3. Files >300 lines
4. Functions >50 lines
5. Dead code (commented-out blocks, unused imports/vars)
6. TODOs without issue links
7. Bare except (`except:` or `except Exception:` without specific handling)
8. Hardcoded secrets, API keys, or environment-specific values
9. Bare `print()` for debugging — use `logging` module (`print()` is acceptable only in CLI entry point output via DBOS CLI mechanism)
10. Untyped function parameters or return values
11. Magic numbers without named constants
12. Adding dependencies for trivial functionality
13. Mixing concerns (feature + refactor + fix in same PR)
14. Swallowed errors (`except: pass`)
15. Copy-paste duplication
16. Overly clever code (nested ternaries, complex comprehensions)
17. Missing docstrings on public functions/classes
18. Test files without assertions
19. Changing files outside the scope of the issue
20. Missing error context (`raise ValueError("failed")` — describe what/why)

21. Reading the whole codebase instead of using the File Map

## File Map

Don't read everything. Start here:

| Task | Read first | Then if needed |
|------|-----------|----------------|
| Change system prompt | `prompts.py` | `toolset_builder.py` (prompt composition + tool wiring) |
| Add a new tool | `tools/_PATTERN.md` | existing `tools/*_tools.py`, then `toolset_builder.py` |
| Fix approval bug | `approval/types.py` | target `approval/*.py` |
| Fix persistence | `store/history.py` or `store/memory.py` | `db.py`, `store/subscriptions.py`, `models.py` |
| Fix streaming/display | `display/streaming.py` | `display/rich_display.py` or `display/stream_formatting.py` |
| Fix agent execution | `agent/runtime.py` | `agent/worker.py` |
| Fix CLI interaction | `agent/cli.py` | `approval/chat_approval.py` |
| Add tests | `tests/conftest.py` | existing test for same module |

## Module Index

> Auto-generate with `./scripts/module-index.sh`

| Module | Description | Lines |
|--------|-------------|-------|
| `chat.py` | Durable CLI chat entrypoint with DBOS-backed queue execution. | 187 |
| `db.py` | Shared SQLite connection helpers for local stores. | 14 |
| `io_utils.py` | Shared file-tail helpers for bounded log reads. | 36 |
| `model_resolution.py` | Model/provider resolution helpers for chat runtime. | 102 |
| `models.py` | Work item types for DBOS-backed priority queue execution. | 103 |
| `prompts.py` | Static system prompt constants for the agent runtime. | 43 |
| `run_simple.py` | Convenience wrapper for `agent.run_sync()` that auto-approves deferred tools. | 92 |
| `skillmaker_tools.py` | Linting and validation helpers for SKILL.md files. | 165 |
| `skills.py` | Filesystem-based skill system with progressive disclosure. | 294 |
| `toolset_builder.py` | Toolset, backend, and workspace wiring for chat runtime. | 203 |
| `agent/cli.py` | Interactive CLI loop and approval handling. | 112 |
| `agent/context.py` | Sliding-window context management with token-based compaction. | 144 |
| `agent/runtime.py` | Agent construction and process runtime state for CLI chat. | 141 |
| `agent/truncation.py` | Truncate large tool results and persist full output to disk. | 92 |
| `agent/worker.py` | DBOS worker and queue helpers for chat work items. | 266 |
| `approval/chat_approval.py` | Approval scope construction and approval decision serialization helpers. | 204 |
| `approval/crypto.py` | Cryptographic helpers for approval signing keys. | 221 |
| `approval/key_files.py` | Filesystem and serialization helpers for approval key material. | 98 |
| `approval/keys.py` | Key management and signing for approval envelopes. | 267 |
| `approval/policy.py` | Immutable tool classification policy for deferred approvals. | 61 |
| `approval/store.py` | SQLite approval envelope storage and verification workflow. | 281 |
| `approval/store_schema.py` | Schema and migration helpers for approval envelope storage. | 123 |
| `approval/store_verify.py` | Verification and parsing helpers for approval submissions. | 161 |
| `approval/types.py` | Shared data models and canonicalization helpers for approval security. | 215 |
| `tools/exec_tool.py` | Shell execution tool with PTY support, timeout, and background mode. | 285 |
| `tools/memory_tools.py` | PydanticAI tool definitions for persistent chat memory. | 95 |
| `tools/process_tool.py` | Process management tool for inspecting and controlling running sessions. | 190 |
| `tools/subscription_tools.py` | PydanticAI tool definitions for subscription management. | 152 |
| `tools/toolset_wrappers.py` | Observable toolset wrapper for logging tool call metrics. | 57 |
| `store/history.py` | SQLite-backed checkpoint store for durable agent message history. | 129 |
| `store/memory.py` | SQLite FTS5-backed persistent memory store for cross-session knowledge. | 253 |
| `store/subscriptions.py` | Subscription registry for reactive context injection. | 221 |
| `display/rich_display.py` | Rich live display manager with per-section streaming channels. | 243 |
| `display/stream_formatting.py` | Stream event formatting and forwarding helpers. | 103 |
| `display/streaming.py` | In-process stream handles for real-time work item output. | 239 |
| `infra/exec_registry.py` | In-memory registry for tracked subprocess sessions. | 147 |
| `infra/otel_tracing.py` | OpenTelemetry tracing helpers for autopoiesis. | 112 |
| `infra/pty_spawn.py` | Thin typed wrapper around stdlib pty for async subprocess spawning. | 63 |
| `infra/subscription_processor.py` | History processor that materializes subscriptions before each agent turn. | 173 |
| `infra/work_queue.py` | DBOS queue instances for background agent work. | 20 |
