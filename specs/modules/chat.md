# Module: chat

## Purpose

`src/autopoiesis/cli.py` is the runtime entrypoint. It builds the agent stack, launches DBOS,
and enters the CLI chat loop. Worker, runtime, and approval helpers are
split into focused companion modules.

## Status

- **Last updated:** 2026-02-18 (Issue #170)
- **Source:** `src/autopoiesis/cli.py`, `agent/runtime.py`, `src/autopoiesis/agent/model_resolution.py`, `src/autopoiesis/tools/toolset_builder.py`, `agent/worker.py`, `infra/approval/chat_approval.py`, `agent/cli.py`

## File Structure

| File | Responsibility |
|------|---------------|
| `src/autopoiesis/cli.py` | Entrypoint, rotate-key command, runtime initialization (all modes), DBOS launch, serve/chat dispatch (≤300 lines) |
| `src/autopoiesis/agent/history.py` | History processor pipeline construction (extracted from chat.py) |
| `src/autopoiesis/agent/runtime.py` | Runtime singleton state, `AgentOptions`, agent assembly, instrumentation toggle |
| `src/autopoiesis/agent/model_resolution.py` | Provider detection, required env access, model settings/env parsing, fallback model resolution |
| `src/autopoiesis/tools/toolset_builder.py` | Workspace/backend creation, console+skills+exec+subscription toolset composition, strict tool schema preparation |
| `src/autopoiesis/agent/worker.py` | DBOS workflow/step functions, enqueue helpers, history serialization |
| `src/autopoiesis/infra/approval/chat_approval.py` | Approval scope, request/result serialization, CLI approval collection |
| `src/autopoiesis/agent/cli.py` | Interactive CLI loop and approval re-enqueue flow |
| `agent/batch.py` | Non-interactive batch execution with deferred approvals disabled and JSON output |
| `src/autopoiesis/models.py` | `AgentDeps`, `WorkItem`, `WorkItemInput`, `WorkItemOutput`, priority/type enums |
| `src/autopoiesis/skills/skills.py` | Skill discovery, progressive loading, skills toolset |
| `src/autopoiesis/infra/work_queue.py` | Queue instance only (no functions importing from `src/autopoiesis/cli.py`) |
| `src/autopoiesis/display/streaming.py` | `StreamHandle` protocol, `RichStreamHandle`, registry |

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
| `AGENT_WORKSPACE_ROOT` | No | `data/agent-workspace` | `toolset_builder.resolve_workspace_root()` | Resolves from `src/autopoiesis/cli.py` dir |
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
| `SKILLS_DIR` | No | `skills` | `toolset_builder._resolve_shipped_skills_dir()` | Shipped skills path, resolves from `src/autopoiesis/cli.py` dir |
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
  that resolves model fallback, provider-specific tool preparation, history processors, and model settings.
- `toolset_builder.strict_tool_definitions(...)` — marks the first `_MAX_STRICT_TOOLS` (20) tools `strict=True`; this callback is applied only when the selected provider is `openrouter`
- `chat_runtime.instrument_agent(agent)` — Enables OpenTelemetry instrumentation when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Returns `True` if applied.

- `_resolve_startup_config()` — resolves provider, agent name, and DBOS system database URL from env
- `toolset_builder.prepare_toolset_context(history_db_path)` — initializes stores (subscriptions, knowledge, topics) and builds toolsets (moved from chat.py)
- **Config loading (Phase B):** When `--config` flag or `AUTOPOIESIS_AGENTS_CONFIG` env var is set, `main()` calls `load_agent_configs(config_path)` and stores results in a module-level `_agent_configs` registry accessible via `get_agent_configs()`. No config → backward-compatible single-agent behavior.
- `agent.history.build_history_processors(...)` — builds ordered message history processors (truncation, compaction, subscriptions, topics, checkpointing) (moved from chat.py)
- `_initialize_runtime(base_dir, *, require_approval_unlock)` — full runtime init for all modes (chat/batch/serve); assembles provider, backend, toolsets, agent, initializes history storage, registers runtime. Serve mode defaults to `require_approval_unlock=False`.
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

- `display_approval_requests(requests_json)` — display pending tool calls
  with tool name and full arguments; returns parsed approval payload
- `gather_approvals(payload, approval_store, key_manager)` — prompt user for y/n on each tool call,
  persist signed approval object + signature on the envelope, then return
  serialized submission (`nonce` + per-call decisions)
  (supports approve-all, deny-all, or pick individually); returns serialized
  approval decisions

### Batch Mode

- `run_batch(task, output_path, timeout)` — execute a single task non-interactively
  using `run_simple(..., auto_approve_deferred=False)`, produce structured
  JSON output, and exit
  with code 0 (success) or 1 (failure). Supports stdin input (`--task -`), file output
  (`--output`), and SIGALRM-based timeout (`--timeout`).
- `format_output(result)` — serialize `BatchResult` to JSON
- `BatchResult` dataclass — success, result text, error, approval_rounds, elapsed_seconds

### CLI

- `cli_chat_loop()` — interactive loop with approval flow. Each message →
  `WorkItem` with CRITICAL priority + `RichStreamHandle` →
  `enqueue_and_wait()`. If output contains `deferred_tool_requests_json`,
  displays pending tool calls, gathers user approval, and re-enqueues with
  `deferred_tool_results_json` until a final text response is received.
  History flows through `WorkItemInput.message_history_json`. Approval scope
  continuity flows through `WorkItemInput.approval_context_id`.

### Entrypoint

- `main()` — load .env → optional `rotate-key` command path → optional `serve` command →
  build stack → set runtime → if `run` command: batch execution (no DBOS, no approval unlock);
  otherwise: unlock approval key → DBOS launch → chat loop
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

## Batch Mode Execution

Batch mode (`run` subcommand) uses direct agent execution via `run_simple()`
for simplicity. Durability guarantees (crash recovery, retry) do not apply to
batch runs. This is intentional: batch tasks are single-shot and short-lived;
the calling process (CI, scripts) handles retry at a higher level.

Batch mode does not require approval key unlock. It operates with FREE-tier
shell access and explicitly rejects deferred approval requests with
`RuntimeError("Deferred approvals unsupported in this mode")`.

## Security Model

Shell command execution is subject to tier-based enforcement. See
`specs/modules/security.md` for the full tier enforcement rules, Docker
exception, and `--no-approval` behavior.

## Invariants

- All **interactive** work goes through the queue. Batch mode (`run` subcommand)
  is an intentional exception — it uses direct `run_simple()` / `agent.run_sync()`.
- Batch mode must call `run_simple(..., auto_approve_deferred=False)`.
- All agent calls use `output_type=[str, DeferredToolRequests]`.
- Required env vars fail with `SystemExit`, not `KeyError`.
- `.env` loads relative to `src/autopoiesis/cli.py`, not CWD.
- Workspace root resolves relative to `src/autopoiesis/cli.py` when not absolute.
- Skills load from shipped + custom locations; custom directory defaults to
  `<AGENT_WORKSPACE_ROOT>/skills`.
- Backend execute always disabled. Write approval always required.
- Console deps contract validated at startup.
- Workflow/step functions live in `agent/worker.py` and are imported by entrypoint flow.
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

- 2026-02-18: Added explicit deferred-approval behavior for non-interactive
  execution. `run_simple()` gained `auto_approve_deferred`, batch mode now
  disables auto-approval, and docs now reflect deterministic batch failure on
  deferred requests. (Issue #170)
- 2026-02-16: `build_agent()` now applies strict tool schema preparation only for
  `AI_PROVIDER=openrouter`. Anthropic runs without strict tool forcing to avoid
  provider-side schema compilation failures with larger toolsets. Worker execution
  now wraps `AgentRunError` as a built-in `RuntimeError` before returning across
  DBOS workflow boundaries, preventing `ModelHTTPError` pickle deserialization
  failures in `handle.get_result()`. (Issue #141)
- 2026-02-16: OTEL insecure flag made configurable via
  `OTEL_EXPORTER_OTLP_INSECURE` env var (Issue #82)
- 2026-02-16: Headless passphrase support via `APPROVAL_KEY_PASSPHRASE`
  env var in `approval_keys.py` (Issue #86)
- 2026-02-16: CLI argparse with `--help`, `--version`, `--no-approval`,
  `--config` flags in `src/autopoiesis/cli.py` (Issue #87, #146).
  `--config` accepts a path to `agents.toml` for multi-agent configuration
  (parsed but not yet wired into runtime — Phase B-2).
- 2026-02-16: Fixed spec drift — function references, class names,
  OVERVIEW.md module index (Issue #81)

- 2026-02-16: Replaced mutable module-global runtime singleton with
  `RuntimeRegistry` in `agent/runtime.py`. Runtime access now uses
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
- 2026-02-16: Added ``run_simple`` convenience module (``src/autopoiesis/run_simple.py``) that
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
- 2026-02-18: Introduced typed `DeferredApprovalLockedError` in `agent/worker.py`
  to replace string-matching heuristic for locked approval key detection.
  Server routes now catch the typed exception directly. (PR #184)
- 2026-02-16: Replaced module-global active checkpoint state with
  context-local `ContextVar` storage for safer worker execution.
  (Issue #21, PR #23)
- 2026-02-16: Refactored chat runtime into `agent/runtime.py`,
  `agent/worker.py`, `infra/approval/chat_approval.py`, and `agent/cli.py` to reduce file
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
  (`python -m autopoiesis.cli rotate-key`) that expires pending envelopes.
  (Issue #19)
- 2026-02-15: Skill system integration. `AgentDeps` moved to `src/autopoiesis/models.py`.
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
  `agent.run` spans in `agent/worker.py` with model/provider/workflow
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

- 2026-02-16: Exposed test hooks in `agent/runtime.py` to eliminate `# pyright: ignore`
  suppressions in test files. (Issue #77)
- 2026-02-16: Replaced inline WAL pragma in `approval_store.py` with shared `open_db()`;
  added proper `Row` typing in `approval_store_schema.py` migration. (Issues #84, #91)
- 2026-02-16: Code smell cleanup — improved error messages, removed defensive checks,
  narrowed exception handling, cached regex. (Issue #89)

### Changelog
- 2026-02-16: Integrated topic system — TopicRegistry init, topic processor in history pipeline (#129)
- 2026-02-16: Modules moved into subdirectories (`agent/`, `approval/`, `display/`, `infra/`, `store/`, `tools/`) as part of subdirectory restructuring (#119)
- 2026-02-16: Added Dependencies/Wired-in docstring headers (#121)
- 2026-02-16: Added `serve` subcommand for FastAPI server mode (#126)
- 2026-02-16: Non-interactive batch mode via `run` subcommand with auto-approval,
  structured JSON output, timeout, and exit codes (#138)
- 2026-02-16: Knowledge system integration — startup indexing, knowledge tools wiring, memory store deprecated (#130)


## Agent Identity Propagation (#200)

Runtime now propagates the selected agent identity through the full stack:
- `cli.py`: resolves agent name from config, passes to runtime
- `runtime.py`: stores agent_id, uses it for WorkItem routing
- `worker.py`: tags outbound messages with agent identity


## AgentConfig Wiring (#201)

AgentConfig is now source of truth for runtime construction:
- Model resolution from config (Anthropic, OpenRouter, passthrough)
- Tool filtering via config whitelist
- Shell tier from config
- System prompt file override
- Backward compatible when no config present


## Agent-Aware Toolset (#202)

Toolset initialization is now agent-aware:
- `prepare_toolset_context_for_agent(agent_id)` derives isolated workspace per agent
- `build_backend_for_agent(agent_workspace)` scoped to agent's workspace subtree
- Per-agent exec-log cleanup

## Verification Criteria

Bidirectional traceability enforced by `scripts/rtm_check.py` in CI.
Tests annotated with `@pytest.mark.verifies("<ID>")` are checked against this table.

| ID | Criterion | Priority | Type |
|----|-----------|----------|------|
| CHAT-V1 | Agent identity propagates to WorkItem.agent_id from runtime agent_name | must | integration |
| CHAT-V2 | Unknown/unsupported provider fails fast with actionable SystemExit error | must | unit |
| CHAT-V3 | Required env var (e.g. ANTHROPIC_API_KEY) fails with SystemExit, not KeyError | must | unit |
| CHAT-V4 | Batch mode exits 0 on success and 1 on failure/error | must | unit |
| CHAT-V5 | FallbackModel wraps both providers when both API keys are present | should | unit |
| CHAT-V6 | Agent name resolution ignores DBOS_AGENT_NAME — uses AUTOPOIESIS_AGENT or CLI flag | must | unit |
| CHAT-V7 | Config-less startup defaults agent name to 'default' (backward compatible) | must | unit |
| CHAT-V8 | OTEL instrumentation is enabled only when OTEL_EXPORTER_OTLP_ENDPOINT is set | may | unit |
