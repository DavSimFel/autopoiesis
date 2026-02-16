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

## Safety

- **Workspace sandbox**: all paths validated with `Path.resolve().is_relative_to(workspace_root)`
- **Approval flow**: tools registered as side-effecting → go through `DeferredToolRequests`
- **Feature gate**: `ENABLE_EXECUTE` env var (default `false`)
- **Timeout**: default 30s with kill
- **Env blocklist**: `_DANGEROUS_ENV_VARS` frozenset blocks `LD_PRELOAD`, `PYTHONPATH`, etc.
- **Log cleanup**: `cleanup_exec_logs(max_age_hours)` runs at startup

## References

- Issue: #24
- OpenClaw: `bash-tools.exec-runtime.ts`, `bash-process-registry.ts`

## Tool Descriptions

All exec and process tools include comprehensive docstrings with usage guidance,
parameter semantics, and cross-references. These docstrings are surfaced to the
agent model as tool descriptions.
