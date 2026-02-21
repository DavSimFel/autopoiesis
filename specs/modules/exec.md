# Shell Execution Module

## Overview

Shell execution with background process management, PTY support, and queue integration. Processes run **outside** the DBOS queue — they are ephemeral, not durable. `exec_tool` and `process_tool` are the authoritative shell/process interfaces.

## Files

| File | Responsibility |
|------|---------------|
| `pty_spawn.py` | Typed wrapper around stdlib `pty.openpty()` for PTY subprocess spawning |
| `exec_registry.py` | In-memory `ProcessSession` registry (add/get/list/mark_exited/cleanup) |
| `exec_tool.py` | `execute` and `execute_pty` tools — spawn, timeout, background, sandbox |
| `process_tool.py` | `process_manager` tool — list/poll/log/write/send-keys/kill |

## Architecture

### Execution Model

```
Queue Worker → Agent Turn → exec tool → spawn process (direct, not via DBOS)
                          → tool returns session ID + initial output
```

- Foreground: process runs to completion (or timeout), output returned directly
- Background: process spawned, session ID returned immediately, output written to `.tmp/exec/<session-id>.log`

### Background Exit Callback

When a background process exits, a `WorkItem` with `type=EXEC_CALLBACK` and `priority=HIGH` is enqueued containing exit code, log path, and last 5 lines of output.

### PTY Support

Uses stdlib `pty.openpty()` — zero external dependencies. Enables interactive CLIs (coding agents, REPLs). The `process_manager` tool's `send-keys` and `write` actions interact with PTY sessions.

## Toolset Composition

- **Dynamic visibility**: `PreparedToolset` hides all exec tools when `ENABLE_EXECUTE` is not set — no contradictory instruction text needed
- **Dynamic approval**: `ApprovalRequiredToolset` with a predicate that skips approval for read-only tools (`process_list`, `process_poll`, `process_log`) and requires it for mutating tools
- **Docstring enforcement**: `docstring_format="google"` + `require_parameter_descriptions=True` on the `FunctionToolset`

## Safety

- **Workspace sandbox**: all paths validated with `Path.resolve().is_relative_to(workspace_root)`
- **Approval flow**: mutating tools require approval via `ApprovalRequiredToolset` predicate
- **Feature gate**: `ENABLE_EXECUTE` env var (default `false`) — tools hidden dynamically via `PreparedToolset`
- **Timeout**: default 30s with kill
- **Process cap**: sandbox default `RLIMIT_NPROC` target is `512`; pre-exec limit application never lowers below the inherited soft limit.
- **Env blocklist**: `_DANGEROUS_ENV_VARS` blocks `ANTHROPIC_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `DATABASE_URL`, `DB_PASSWORD`, `GITHUB_TOKEN`, `LD_PRELOAD`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `PASSWORD`, `PRIVATE_KEY`, `PYTHONPATH`, and `SECRET_KEY`. Explicit `env` values containing these keys are rejected; omitted `env` inherits parent vars with these keys removed.
- **Log cleanup**: `cleanup_exec_logs(max_age_hours)` runs at startup

## Observability

- All exec and process tools carry `metadata={"category": "exec"}` or `{"category": "process"}` for toolset-level observability.
- `execute` and `execute_pty` return `ToolReturn` (not raw dicts) with structured metadata (`session_id`, `log_path`, `exit_code`).
- `process_log` returns `ToolReturn` with log content as `return_value` and metadata (`session_id`, `log_path`, `total` line count).

## Change Log

- 2026-02-21: Extracted `exec_env.py` from `exec_tool.py` (environment sanitization
  helpers: `validate_env`, `resolve_env`). Architecture violation fix.
- 2026-02-21: Raised sandbox default process limit from 64 to 512 and updated
  RLIMIT application to preserve inherited soft limits (never lower on pre-exec).
  (Issue #221)
- 2026-02-18: Removed legacy `shell_tool` path from documentation; exec/process
  tools are now the only supported command-execution interfaces. (Issue #170)
- 2026-02-16: Replaced module-level mutable session dict in
  `exec_registry.py` with a lock-protected `ExecRegistry` class and
  injectable registry helpers (`get_registry()` / `set_registry()`).
  Existing module API (`add/get/list_sessions/mark_exited/reset`) now
  delegates to the active registry instance for safer concurrent access
  and easier test isolation. (Issue #83)
- 2026-02-16: Fixed `execute`/`execute_pty` env inheritance to filter dangerous
  parent vars when `env` is omitted, and aligned `_DANGEROUS_ENV_VARS` with
  `LD_PRELOAD` + `PYTHONPATH`. (Issue #78)
- 2026-02-16: Replaced full-file reads in `_tail_lines` and `_read_tail` with
  seek-based bounded reads. `process_log` uses streaming line-slice instead of
  loading entire log into memory. Deleted dead `approval_security.py` shim.
  Guarded `dbos` import in `src/autopoiesis/infra/work_queue.py` with fail-fast `SystemExit`. (Issue #45)
- 2026-02-16: Fixed `sandbox_cwd` path confinement to use `Path.is_relative_to()`
  instead of string prefix matching, preventing sibling-directory escape. (Issue #42)

## References

- Issue: #24
- OpenClaw: `bash-tools.exec-runtime.ts`, `bash-process-registry.ts`

- 2026-02-16: Code smell cleanup — improved error messages, removed defensive checks,
  narrowed exception handling, cached regex. (Issue #89)

### Changelog
- 2026-02-16: Modules moved into subdirectories (`agent/`, `approval/`, `display/`, `infra/`, `store/`, `tools/`) as part of subdirectory restructuring (#119)
- 2026-02-16: Added Dependencies/Wired-in docstring headers as part of #121 documentation update
- 2026-02-20: Added result_store.py to store/ — persistent storage for tool results and shell outputs, wired into exec_tool.py and agent/worker.py (#212)

## PTY Sandbox (#227)
- preexec_fn parameter for sandbox enforcement in PTY sessions
