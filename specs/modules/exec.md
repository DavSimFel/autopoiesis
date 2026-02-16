# Shell Execution Module

## Overview

Shell execution with background process management, PTY support, and queue integration. Processes run **outside** the DBOS queue — they are ephemeral, not durable.

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
- **Env blocklist**: `_DANGEROUS_ENV_VARS` frozenset blocks `LD_PRELOAD`, `PYTHONPATH`, etc.
- **Log cleanup**: `cleanup_exec_logs(max_age_hours)` runs at startup

## Observability

- All exec and process tools carry `metadata={"category": "exec"}` or `{"category": "process"}` for toolset-level observability.
- `execute` and `execute_pty` return `ToolReturn` (not raw dicts) with structured metadata (`session_id`, `log_path`, `exit_code`).
- `process_log` returns `ToolReturn` with log content as `return_value` and metadata (`session_id`, `log_path`, `total` line count).

## Change Log

- 2026-02-16: Fixed `sandbox_cwd` path confinement to use `Path.is_relative_to()`
  instead of string prefix matching, preventing sibling-directory escape. (Issue #42)

## References

- Issue: #24
- OpenClaw: `bash-tools.exec-runtime.ts`, `bash-process-registry.ts`
