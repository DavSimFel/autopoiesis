# Module: chat

## Purpose

`chat.py` is the runtime entrypoint. It builds the agent stack, launches DBOS,
and enters the CLI chat loop. Worker, runtime, and approval helpers are
split into focused companion modules.

## Status

- **Last updated:** 2026-02-16 (Issue #76)
- **Source:** `chat.py`, `chat_runtime.py`, `model_resolution.py`, `toolset_builder.py`, `chat_worker.py`, `chat_approval.py`, `chat_cli.py`

## File Structure

| File | Responsibility |
|------|---------------|
| `chat.py` | Entrypoint, rotate-key command, DBOS launch, runtime wiring |
| `chat_runtime.py` | Runtime singleton state, `AgentOptions`, agent assembly, instrumentation toggle |
| `model_resolution.py` | Provider detection, required env access, model settings/env parsing, fallback model resolution |
| `toolset_builder.py` | Workspace/backend creation, console+skills+exec+memory/subscription toolset composition, strict tool schema preparation |
| `chat_worker.py` | DBOS workflow/step functions, enqueue helpers, history serialization |
| `chat_approval.py` | Approval scope, request/result serialization, CLI approval collection |
| `chat_cli.py` | Interactive CLI loop and approval re-enqueue flow |
| `models.py` | `AgentDeps`, `WorkItem`, `WorkItemInput`, `WorkItemOutput`, priority/type enums |
| `skills.py` | Skill discovery, progressive loading, skills toolset |
| `work_queue.py` | Queue instance only (no functions importing from `chat.py`) |
| `streaming.py` | `StreamHandle` protocol, `RichStreamHandle`, registry |

## Environment Variables

| Var | Required | Default | Used in | Notes |
|-----|----------|---------|---------|-------|
| `AI_PROVIDER` | No | `anthropic` | `main()` | Provider selection |
| `ANTHROPIC_API_KEY` | If anthropic | — | `model_resolution.resolve_model()` | API key |
| `ANTHROPIC_MODEL` | No | `anthropic:claude-3-5-sonnet-latest` | `model_resolution.resolve_model()` | Model string |
| `OPENROUTER_API_KEY` | If openrouter | — | `model_resolution.resolve_model()` | API key |
| `OPENROUTER_MODEL` | No | `openai/gpt-4o-mini` | `model_resolution.resolve_model()` | Model id |
| `AI_TEMPERATURE` | No | — | `model_resolution.build_model_settings()` | LLM sampling temperature |
| `AI_MAX_TOKENS` | No | — | `model_resolution.build_model_settings()` | Max generation tokens |
| `AI_TOP_P` | No | — | `model_resolution.build_model_settings()` | Nucleus sampling top-p |
| `AGENT_WORKSPACE_ROOT` | No | `data/agent-workspace` | `toolset_builder.resolve_workspace_root()` | Resolves from `chat.py` dir |
| `DBOS_APP_NAME` | No | `pydantic_dbos_agent` | `main()` | DBOS app name |
| `DBOS_AGENT_NAME` | No | `chat` | `main()` | Agent name |
| `DBOS_SYSTEM_DATABASE_URL` | No | `sqlite:///dbostest.sqlite` | `main()` | DBOS database URL |
| `APPROVAL_DB_PATH` | No | `data/approvals.sqlite` | `ApprovalStore.from_env(base_dir=...)` | Optional SQLite override for approval envelopes |
| `APPROVAL_TTL_SECONDS` | No | `3600` | `ApprovalStore.from_env(base_dir=...)` | Approval expiry window in seconds |
| `APPROVAL_KEY_DIR` | No | `data/keys` | `ApprovalKeyManager.from_env(base_dir=...)` | Base directory for approval key material |
| `APPROVAL_PRIVATE_KEY_PATH` | No | `$APPROVAL_KEY_DIR/approval.key` | `ApprovalKeyManager.from_env(base_dir=...)` | Encrypted Ed25519 private key path |
| `APPROVAL_PUBLIC_KEY_PATH` | No | `$APPROVAL_KEY_DIR/approval.pub` | `ApprovalKeyManager.from_env(base_dir=...)` | Active public key path |
| `APPROVAL_KEYRING_PATH` | No | `$APPROVAL_KEY_DIR/keyring.json` | `ApprovalKeyManager.from_env(base_dir=...)` | Active/retired verification keyring |
| `NONCE_RETENTION_PERIOD_SECONDS` | No | `604800` | `ApprovalStore.from_env(base_dir=...)` | Expired envelope pruning horizon |
| `APPROVAL_CLOCK_SKEW_SECONDS` | No | `60` | `ApprovalStore.from_env(base_dir=...)` | Startup invariant with retention + TTL |
| `SKILLS_DIR` | No | `skills` | `toolset_builder._resolve_shipped_skills_dir()` | Shipped skills path, resolves from `chat.py` dir |
| `CUSTOM_SKILLS_DIR` | No | `skills` | `toolset_builder._resolve_custom_skills_dir()` | Custom skills path, resolves inside `AGENT_WORKSPACE_ROOT` when relative |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | — | `chat_runtime.instrument_agent()` | When set, enables OpenTelemetry trace export via `agent.instrument()` |

## Functions

### Startup

- `model_resolution.required_env(name)` — fail-fast env var read
- `model_resolution.resolve_provider(provider)` — validated provider selection (`anthropic` or `openrouter`)
- `model_resolution.build_model_settings()` — parses optional `AI_*` generation settings
- `model_resolution.resolve_model(provider)` — primary/fallback model resolution
- `toolset_builder.resolve_workspace_root()` — resolve + create workspace dir
- `toolset_builder._resolve_shipped_skills_dir()` — resolve shipped skills directory (default: `skills/`)
- `toolset_builder._resolve_custom_skills_dir()` — resolve custom skills directory inside workspace (default: `skills/`)
- `toolset_builder._build_skill_directories()` — build skill directory list in precedence order (shipped first, custom second)
- `toolset_builder.build_backend()` — `LocalBackend` with execute disabled
- `toolset_builder.validate_console_deps_contract()` — structural typing guard
- `toolset_builder.build_toolsets()` — returns `(toolsets, instructions)`. Console toolset
  (write approval) + skills toolset from shipped and custom directories.
  Custom skills override shipped skills when names collide.
- `chat_runtime.build_agent(provider, name, toolsets, system_prompt, options)` — Anthropic/OpenRouter factory
  that resolves model fallback, strict tool preparation, history processors, and model settings.
- `toolset_builder.strict_tool_definitions(...)` — marks the first `_MAX_STRICT_TOOLS` (20) tools `strict=True` for OpenAI-compatible providers; remaining tools stay non-strict to respect Anthropic's limit
- `chat_runtime.instrument_agent(agent)` — Enables OpenTelemetry instrumentation when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Returns `True` if applied.

### Runtime State

- `Runtime` dataclass holds agent + backend + approval store + unlocked key manager + tool policy for the process lifetime
- `RuntimeRegistry` provides lock-protected runtime storage with
  `set_runtime()` / `get_runtime()` wrappers for application code
- `set_runtime_registry()` / `get_runtime_registry()` allow test injection
  and `reset_runtime()` clears process runtime in tests
- `_CheckpointContext` + `ContextVar` store active checkpoint metadata per
  execution context for history processor writes

### Deferred Tool Serialization

- `build_approval_scope(approval_context_id, backend, agent_name)` — build live
  execution scope for approval hashing/verification
- `serialize_deferred_requests(requests, scope, approval_store, key_manager, tool_policy)` —
  validate deferred calls against immutable tool policy, persist a nonce-bound
  envelope with `key_id`, and serialize nonce + plan hash prefix + tool calls
- `deserialize_deferred_results(results_json, scope, approval_store, key_manager)` —
  verify signature-first + context drift + bijection + atomic nonce consume, then reconstruct
  `DeferredToolResults`

### Queue Workers

- `run_agent_step(work_item_dict)` — `@DBOS.step()`. Passes
  `output_type=[str, DeferredToolRequests]` to all agent calls. Checks for
  stream handle: if present, uses `agent.run_stream_sync()` for real-time output;
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
- `_gather_approvals(payload, approval_store, key_manager)` — prompt user for y/n on each tool call,
  persist signed approval object + signature on the envelope, then return
  serialized submission (`nonce` + per-call decisions)
  (supports approve-all, deny-all, or pick individually); returns serialized
  approval decisions

### CLI

- `cli_chat_loop()` — interactive loop with approval flow. Each message →
  `WorkItem` with CRITICAL priority + `RichStreamHandle` →
  `enqueue_and_wait()`. If output contains `deferred_tool_requests_json`,
  displays pending tool calls, gathers user approval, and re-enqueues with
  `deferred_tool_results_json` until a final text response is received.
  History flows through `WorkItemInput.message_history_json`. Approval scope
  continuity flows through `WorkItemInput.approval_context_id`.

### Entrypoint

- `main()` — load .env → optional `rotate-key` command path → unlock approval key
  (required) → build stack → set runtime → DBOS launch → chat loop
- `_rotate_key(base_dir)` — interactive key rotation; invalidates pending envelopes

## Deferred Tool Approval Flow

1. Agent calls a tool with `require_write_approval=True`
2. PydanticAI returns `DeferredToolRequests` instead of executing the tool
3. Worker validates deferred tool classifications (read-only tools in deferred requests are rejected)
4. Worker serializes requests into `WorkItemOutput.deferred_tool_requests_json`
5. Worker stores an approval envelope (nonce + scope + tool calls + plan hash + key_id)
6. CLI displays full tool args + plan hash prefix, prompts user for approval
7. CLI signs canonical signed object and persists signature on the envelope
8. CLI re-enqueues a new `WorkItem` with nonce + approval decisions
9. Worker verifies signature/key first, then context hash and decision bijection,
   then atomically consumes nonce and reconstructs `DeferredToolResults`
10. Agent executes approved tools, gets denial messages for denied ones
11. Loop repeats until agent returns a final `str` response

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
- Workflow/step functions live in `chat_worker.py` and are imported by entrypoint flow.
- Stream handles are in-process only — not durable, not serialised.
- Deferred approvals are nonce-bound and single-use (atomic consume in SQLite).
- Agent execution is blocked unless approval signing key is unlocked at startup.
- No approval execution path exists without a persisted envelope signature.
- Invalid/tampered approval submissions are rejected before nonce consumption.
- Unknown tool names default to side-effecting in deferred tool classification.
- Deferred tool requests/results are serialized as JSON for queue transport.

## Dependencies

- `pydantic-ai-slim[openai,anthropic,cli,dbos,mcp]>=1.59,<2`
- `pydantic-ai-backend==0.1.6`
- `python-dotenv>=1.2,<2`

## Change Log

- 2026-02-16: OTEL insecure flag made configurable via
  `OTEL_EXPORTER_OTLP_INSECURE` env var (Issue #82)
- 2026-02-16: Headless passphrase support via `APPROVAL_KEY_PASSPHRASE`
  env var in `approval_keys.py` (Issue #86)
- 2026-02-16: CLI argparse with `--help`, `--version`, `--no-approval`
  flags in `chat.py` (Issue #87)
- 2026-02-16: Fixed spec drift — function references, class names,
  OVERVIEW.md module index (Issue #81)

- 2026-02-16: Replaced mutable module-global runtime singleton with
  `RuntimeRegistry` in `chat_runtime.py`. Runtime access now uses
  lock-protected registry storage with injectable helpers
  (`get_runtime_registry()` / `set_runtime_registry()`) and explicit
  `reset_runtime()` support for tests. Existing `get_runtime()` /
  `set_runtime()` call sites remain stable wrappers. (Issue #83)
- 2026-02-16: FallbackModel for provider resilience. When both
  `ANTHROPIC_API_KEY` and `OPENROUTER_API_KEY` are set, wraps primary
  and alternate models in `FallbackModel` for automatic retry on provider
  failure. `AI_PROVIDER` controls which is primary. (Issue #57)
- 2026-02-16: Added sliding-window context compaction and tool-result truncation
  as history processors. New modules: `context_manager.py`,
  `tool_result_truncation.py`. See `specs/modules/context.md`. (Issue #27)
- 2026-02-16: Hardened SQLite reliability in approval, memory, and history stores.
  Connections now use explicit close semantics (`contextlib.closing` with
  transactional context), and each connection sets `PRAGMA journal_mode=WAL`
  on open. (Issue #44)
- 2026-02-16: Added `ObservableToolset` wrapper (`toolset_wrappers.py`) that
  intercepts all tool calls to log name, duration, and outcome. All toolsets
  returned by `build_toolsets()` are now wrapped for observability. Tool
  metadata categories added across exec, process, memory, and skill tools.
  Exec/process tools return `ToolReturn` with structured metadata instead of
  raw dicts. (Issue #38, PR #39)
- 2026-02-16: Added optional OpenTelemetry instrumentation via
  `instrument_agent()`. When `OTEL_EXPORTER_OTLP_ENDPOINT` is set,
  `agent.instrument()` exports traces to the configured OTLP collector.
  Complementary to existing `ObservableToolset`. (Issue #60)
- 2026-02-16: Added ``run_simple`` convenience module (``run_simple.py``) that
  wraps ``agent.run_sync()`` with automatic deferred-tool approval for testing
  and scripting use cases.  Calling ``run_sync()`` directly without
  ``output_type=[str, DeferredToolRequests]`` crashes with a ``UserError``;
  ``run_simple()`` handles this transparently.
  (Issue #61)
- 2026-02-16: Added `build_model_settings()` to read `AI_TEMPERATURE`,
  `AI_MAX_TOKENS`, `AI_TOP_P` from env vars and pass as `ModelSettings` to
  the agent. Set `end_strategy='exhaustive'` on all agents for reliable
  tool execution when model returns text alongside tool calls.
  (Issue #55, Issue #56)
- 2026-02-16: Replaced module-global active checkpoint state with
  context-local `ContextVar` storage for safer worker execution.
  (Issue #21, PR #23)
- 2026-02-16: Refactored chat runtime into `chat_runtime.py`,
  `chat_worker.py`, `chat_approval.py`, and `chat_cli.py` to reduce file
  size and isolate responsibilities while preserving queue-based behavior.
  (Issue #19, PR #20)
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
- 2026-02-15: Phase 1 security completion wiring. Approval flow now requires
  unlocked Ed25519 signing key at startup, stores envelope `key_id`, signs
  approval decisions before re-enqueue, verifies signature before consume, and
  enforces immutable tool classification defaults. Added key rotation command
  (`python chat.py rotate-key`) that expires pending envelopes.
  (Issue #19)
- 2026-02-15: Skill system integration. `AgentDeps` moved to `models.py`.
  `build_toolsets()` returns `(toolsets, instructions)`. `build_agent()`
  accepts instructions list, passes to PydanticAI `instructions` param.
  `SKILLS_DIR` env var. (Issue #9)
- 2026-02-15: Deferred tool approval flow. Agent calls with
  `output_type=[str, DeferredToolRequests]`. CLI gathers human approval
  and re-enqueues. `WorkItemInput` gains `deferred_tool_results_json`,
  `WorkItemOutput` gains `deferred_tool_requests_json`. (Issue #16)
- 2026-02-16: SigNoz observability stack and custom OTEL span attributes.
  Added `docker/docker-compose.signoz.yml` for local SigNoz dev setup,
  `otel_tracing.py` module for SDK bootstrap and span helpers, custom
  `agent.run` spans in `chat_worker.py` with model/provider/workflow
  attributes, and `docs/observability.md`. (Issue #70)
- 2026-02-15: Unified all work through priority queue. WorkItem model with
  structured input/output. Stream handles for real-time CLI output. Removed
  `to_cli_sync()` / `DBOSAgent`. (Issue #8)

## Prompt Semantics

### Approval Resume

When resuming after an approval decision, the prompt is `None` (not empty string).
PydanticAI treats `None` as a follow-up turn with no new user input, while `""` adds a
meaningless empty user message that can skew tool-call behavior.

### Capability Instructions

Capability text (exec, memory, skills) is generated conditionally based on what's
actually enabled. No contradictory "disabled/enabled" text is emitted. Instructions
describe actual enforcement honestly — cwd/path validation, not hard sandbox.

- 2026-02-16: Exposed test hooks in `chat_runtime.py` to eliminate `# pyright: ignore`
  suppressions in test files. (Issue #77)
- 2026-02-16: Replaced inline WAL pragma in `approval_store.py` with shared `open_db()`;
  added proper `Row` typing in `approval_store_schema.py` migration. (Issues #84, #91)
- 2026-02-16: Code smell cleanup — improved error messages, removed defensive checks,
  narrowed exception handling, cached regex. (Issue #89)
