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
