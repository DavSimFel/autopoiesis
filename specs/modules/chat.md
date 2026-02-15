# Module: chat

## Purpose

`chat.py` is the runtime entrypoint. It builds the agent stack, launches DBOS,
and enters the CLI chat loop. It also hosts the DBOS workflow/step functions
that execute work items from the queue.

## Status

- **Last updated:** 2026-02-15 (Issue #19)
- **Source:** `chat.py`

## File Structure

| File | Responsibility |
|------|---------------|
| `chat.py` | Startup, agent wiring, DBOS workflow/step, enqueue helpers, approval UI, CLI loop |
| `models.py` | `AgentDeps`, `WorkItem`, `WorkItemInput`, `WorkItemOutput`, priority/type enums |
| `skills.py` | Skill discovery, progressive loading, skills toolset |
| `work_queue.py` | Queue instance only (no functions importing from `chat.py`) |
| `streaming.py` | `StreamHandle` protocol, `PrintStreamHandle`, registry |

## Environment Variables

| Var | Required | Default | Used in | Notes |
|-----|----------|---------|---------|-------|
| `AI_PROVIDER` | No | `anthropic` | `main()` | Provider selection |
| `ANTHROPIC_API_KEY` | If anthropic | — | `build_agent()` | API key |
| `ANTHROPIC_MODEL` | No | `anthropic:claude-3-5-sonnet-latest` | `build_agent()` | Model string |
| `OPENROUTER_API_KEY` | If openrouter | — | `build_agent()` | API key |
| `OPENROUTER_MODEL` | No | `openai/gpt-4o-mini` | `build_agent()` | Model id |
| `AGENT_WORKSPACE_ROOT` | No | `data/agent-workspace` | `resolve_workspace_root()` | Resolves from `chat.py` dir |
| `DBOS_APP_NAME` | No | `pydantic_dbos_agent` | `main()` | DBOS app name |
| `DBOS_AGENT_NAME` | No | `chat` | `main()` | Agent name |
| `DBOS_SYSTEM_DATABASE_URL` | No | `sqlite:///dbostest.sqlite` | `main()` | DBOS database URL |
| `APPROVAL_DB_PATH` | No | derived from `DBOS_SYSTEM_DATABASE_URL` | `ApprovalStore.from_env()` | Optional SQLite override for approval envelopes |
| `APPROVAL_TTL_SECONDS` | No | `3600` | `ApprovalStore.from_env()` | Approval expiry window in seconds |
| `SKILLS_DIR` | No | `skills` | `_resolve_shipped_skills_dir()` | Shipped skills path, resolves from `chat.py` dir |
| `CUSTOM_SKILLS_DIR` | No | `skills` | `_resolve_custom_skills_dir()` | Custom skills path, resolves inside `AGENT_WORKSPACE_ROOT` when relative |

## Functions

### Startup

- `required_env(name)` — fail-fast env var read
- `resolve_workspace_root()` — resolve + create workspace dir
- `_resolve_shipped_skills_dir()` — resolve shipped skills directory (default: `skills/`)
- `_resolve_custom_skills_dir()` — resolve custom skills directory inside workspace (default: `skills/`)
- `_build_skill_directories()` — build skill directory list in precedence order (shipped first, custom second)
- `build_backend()` — `LocalBackend` with execute disabled
- `validate_console_deps_contract()` — structural typing guard
- `build_toolsets()` — returns `(toolsets, instructions)`. Console toolset
  (write approval) + skills toolset from shipped and custom directories.
  Custom skills override shipped skills when names collide.
- `build_agent(provider, name, toolsets, instructions)` — Anthropic or
  OpenRouter factory. Passes instructions to PydanticAI's `instructions`
  parameter for automatic system prompt composition.

### Runtime State

- `_Runtime` dataclass holds agent + backend for the process lifetime
- `_set_runtime()` / `_get_runtime()` — set in `main()`, read by workers
- `_CheckpointContext` + `ContextVar` store active checkpoint metadata per
  execution context for history processor writes

### Deferred Tool Serialization

- `_build_approval_scope(approval_context_id, backend, agent_name)` — build live
  execution scope for approval hashing/verification
- `_serialize_deferred_requests(requests, scope, approval_store)` — persist a
  nonce-bound envelope and serialize nonce + plan hash prefix + tool calls
- `_deserialize_deferred_results(results_json, scope, approval_store)` —
  verify envelope/hash/bijection + atomic nonce consume, then reconstruct
  `DeferredToolResults`

### Queue Workers

- `run_agent_step(work_item_dict)` — `@DBOS.step()`. Passes
  `output_type=[str, DeferredToolRequests]` to all agent calls. Checks for
  stream handle: if present, uses `agent.run_stream()` for real-time output;
  otherwise `agent.run_sync()`. If input carries `deferred_tool_results_json`,
  passes reconstructed approvals to the agent. Returns `WorkItemOutput` as dict.
- `execute_work_item(work_item_dict)` — `@DBOS.workflow()`. Delegates to
  `run_agent_step()`.

### Enqueue Helpers

- `enqueue(item)` — fire-and-forget, returns work item id
- `enqueue_and_wait(item)` — blocks on `handle.get_result()`, returns `WorkItemOutput`

### CLI Approval Display

- `_display_approval_requests(requests_json)` — display pending tool calls
  with tool name and full arguments; returns parsed approval payload
- `_gather_approvals(payload)` — prompt user for y/n on each tool call
  (supports approve-all, deny-all, or pick individually); returns serialized
  approval decisions

### CLI

- `cli_chat_loop()` — interactive loop with approval flow. Each message →
  `WorkItem` with CRITICAL priority + `PrintStreamHandle` →
  `enqueue_and_wait()`. If output contains `deferred_tool_requests_json`,
  displays pending tool calls, gathers user approval, and re-enqueues with
  `deferred_tool_results_json` until a final text response is received.
  History flows through `WorkItemInput.message_history_json`. Approval scope
  continuity flows through `WorkItemInput.approval_context_id`.

### Entrypoint

- `main()` — load .env → build stack → set runtime → DBOS launch → chat loop

## Deferred Tool Approval Flow

1. Agent calls a tool with `require_write_approval=True`
2. PydanticAI returns `DeferredToolRequests` instead of executing the tool
3. Worker serializes the requests into `WorkItemOutput.deferred_tool_requests_json`
4. Worker stores an approval envelope (nonce + scope + tool calls + plan hash)
5. CLI displays full tool args + plan hash prefix, prompts user for approval
6. CLI re-enqueues a new `WorkItem` with nonce + approval decisions
7. Worker verifies nonce, context hash, and decision bijection; then atomically
   consumes nonce and reconstructs `DeferredToolResults`
8. Agent executes approved tools, gets denial messages for denied ones
9. Loop repeats until agent returns a final `str` response

## Invariants

- All work goes through the queue. No direct `agent.run_sync()` outside workers.
- All agent calls use `output_type=[str, DeferredToolRequests]`.
- Required env vars fail with `SystemExit`, not `KeyError`.
- `.env` loads relative to `chat.py`, not CWD.
- Workspace root resolves relative to `chat.py` when not absolute.
- Skills load from shipped + custom locations; custom directory defaults to
  `<AGENT_WORKSPACE_ROOT>/skills`.
- Backend execute always disabled. Write approval always required.
- Console deps contract validated at startup.
- Workflow/step functions live in `chat.py` to avoid circular imports.
- Stream handles are in-process only — not durable, not serialised.
- Deferred approvals are nonce-bound and single-use (atomic consume in SQLite).
- Invalid approval submissions are rejected before nonce consumption.
- Deferred tool requests/results are serialized as JSON for queue transport.

## Dependencies

- `pydantic-ai-slim[openai,anthropic,cli,dbos,mcp]>=1.59,<2`
- `pydantic-ai-backend==0.1.6`
- `python-dotenv>=1.2,<2`

## Change Log

- 2026-02-16: Replaced module-global active checkpoint state with
  context-local `ContextVar` storage for safer worker execution.
  (Issue #21, PR #23)
- 2026-02-15: Skills now load from two places: shipped skills (`SKILLS_DIR`,
  repo-relative by default) and custom workspace skills (`CUSTOM_SKILLS_DIR`,
  workspace-relative by default). Custom skills override shipped skills by name.
  Added shipped `skillmaker` skill and quality tools for skill lint/validation.
  (Issue #9)
- 2026-02-15: Deferred approval envelopes now persist in SQLite with canonical
  plan hashing, context-drift verification, bijection checks, and atomic
  nonce consumption. Added `APPROVAL_TTL_SECONDS` and optional
  `APPROVAL_DB_PATH` override; default storage follows DBOS SQLite.
  Approval context now uses a stable `approval_context_id` across
  re-enqueued work items, and malformed submissions are rejected before
  nonce consumption.
  (Issue #19)
- 2026-02-15: Skill system integration. `AgentDeps` moved to `models.py`.
  `build_toolsets()` returns `(toolsets, instructions)`. `build_agent()`
  accepts instructions list, passes to PydanticAI `instructions` param.
  `SKILLS_DIR` env var. (Issue #9)
- 2026-02-15: Deferred tool approval flow. Agent calls with
  `output_type=[str, DeferredToolRequests]`. CLI gathers human approval
  and re-enqueues. `WorkItemInput` gains `deferred_tool_results_json`,
  `WorkItemOutput` gains `deferred_tool_requests_json`. (Issue #16)
- 2026-02-15: Unified all work through priority queue. WorkItem model with
  structured input/output. Stream handles for real-time CLI output. Removed
  `to_cli_sync()` / `DBOSAgent`. (Issue #8)
