# Architecture

## 10-Second Overview

Autopoiesis is a durable CLI chat agent built on **PydanticAI** + **DBOS**.
User messages become work items on a priority queue. A DBOS worker executes
each item by running a PydanticAI agent with filesystem, shell, memory, and
subscription tools. Cryptographic approval gates shell execution and filesystem
operations (exec_tool, process_tool); memory and subscription DB operations do
not require approval.
Responses stream back to a Rich terminal UI in real time.

## System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  chat.py  (entrypoint)                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ agent/cli    │→│ agent/worker │→│  agent/runtime     │  │
│  │ (REPL loop)  │  │ (DBOS queue) │  │  (agent builder)  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘  │
│         │                 │                    │             │
│         ▼                 ▼                    ▼             │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ display/     │  │ approval/    │  │ toolset_builder   │  │
│  │ streaming    │  │ (crypto gate)│  │ (tool wiring)     │  │
│  └─────────────┘  └──────────────┘  └────────┬──────────┘  │
│                                               │             │
│                    ┌──────────────────────────┬┘            │
│                    ▼              ▼           ▼             │
│             ┌───────────┐ ┌───────────┐ ┌──────────┐       │
│             │ tools/     │ │ store/    │ │ skills   │       │
│             │ exec,proc  │ │ mem,hist  │ │ subs     │       │
│             └───────────┘ └───────────┘ └──────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow: One Chat Turn

1. **User types** a message at the `>` prompt in `agent/cli.py`
2. `_run_turn()` wraps it in a `WorkItem` (type=CHAT, priority=CRITICAL)
3. A `RichStreamHandle` is registered for the item's id in `display/streaming.py`
4. `enqueue_and_wait()` puts the item on the DBOS `infra/work_queue`
5. DBOS dispatches `execute_work_item()` → `run_agent_step()` in `agent/worker.py`
6. Worker deserializes history, builds `AgentDeps`, constructs `ApprovalScope`
7. `rt.agent.run_stream_sync()` calls the PydanticAI agent with all toolsets
8. Tokens stream through `StreamHandle.write()` → `RichDisplayManager` → terminal
9. If a tool needs approval → agent returns `DeferredToolRequests`, CLI prompts user, re-enqueues
10. On completion, `WorkItemOutput` (text + serialized history) returns to CLI
11. History JSON is carried forward for the next turn

## Module Dependency Graph

```mermaid
graph TD
    chat.py --> agent/cli.py
    chat.py --> agent/runtime.py
    chat.py --> agent/worker.py
    chat.py --> toolset_builder.py
    chat.py --> model_resolution.py
    chat.py --> approval/keys.py
    chat.py --> approval/store.py
    chat.py --> store/history.py
    chat.py --> store/memory.py

    agent/cli.py --> agent/worker.py
    agent/cli.py --> approval/chat_approval.py
    agent/cli.py --> display/streaming.py

    agent/worker.py --> agent/runtime.py
    agent/worker.py --> approval/chat_approval.py
    agent/worker.py --> store/history.py
    agent/worker.py --> display/streaming.py
    agent/worker.py --> display/stream_formatting.py

    agent/runtime.py --> toolset_builder.py
    agent/runtime.py --> model_resolution.py
    agent/runtime.py --> models.py

    toolset_builder.py --> prompts.py
    toolset_builder.py --> tools/memory_tools.py
    toolset_builder.py --> skills.py
    toolset_builder.py --> tools/subscription_tools.py
    toolset_builder.py --> tools/exec_tool.py
    toolset_builder.py --> tools/process_tool.py
    toolset_builder.py --> tools/toolset_wrappers.py

    approval/store.py --> approval/crypto.py
    approval/store.py --> approval/types.py
    approval/store.py --> approval/store_schema.py
    approval/store.py --> approval/store_verify.py
    approval/keys.py --> approval/key_files.py
    approval/keys.py --> approval/crypto.py

    tools/exec_tool.py --> infra/exec_registry.py
    tools/exec_tool.py --> infra/pty_spawn.py
    tools/exec_tool.py --> io_utils.py

    tools/memory_tools.py --> store/memory.py
    tools/subscription_tools.py --> store/subscriptions.py
    infra/subscription_processor.py --> store/subscriptions.py
```

## Package Responsibilities

| Cluster | Files | What it does |
|---------|-------|-------------|
| **Entry & CLI** | `chat.py`, `agent/cli.py` | Arg parsing, env loading, DBOS bootstrap, interactive REPL |
| **Agent Runtime** | `agent/runtime.py`, `agent/worker.py`, `models.py`, `infra/work_queue.py` | Agent construction, DBOS queue worker, work item types, priority queue |
| **Tool Wiring** | `toolset_builder.py`, `tools/toolset_wrappers.py`, `prompts.py` | Assembles all toolsets, composes system prompt, observable wrappers |
| **Exec Tools** | `tools/exec_tool.py`, `tools/process_tool.py`, `infra/exec_registry.py`, `infra/pty_spawn.py`, `io_utils.py` | Shell execution with PTY, process management, session tracking |
| **Memory** | `tools/memory_tools.py`, `store/memory.py` | FTS5-backed persistent memory, search/save/get tools |
| **Skills** | `skills.py`, `skillmaker_tools.py` | Filesystem skill discovery, progressive disclosure, skill linting |
| **Subscriptions** | `tools/subscription_tools.py`, `store/subscriptions.py`, `infra/subscription_processor.py` | Reactive context injection, subscription registry, history materialization |
| **Approval** | `approval/types.py`, `approval/crypto.py`, `approval/keys.py`, `approval/key_files.py`, `approval/policy.py`, `approval/store.py`, `approval/store_schema.py`, `approval/store_verify.py`, `approval/chat_approval.py` | Cryptographic tool approval with Ed25519 signing, envelope storage, policy |
| **Persistence** | `store/history.py`, `store/memory.py`, `db.py` | SQLite checkpoint store, memory FTS5 store, shared DB helpers |
| **Display** | `display/streaming.py`, `display/rich_display.py`, `display/stream_formatting.py` | Real-time Rich terminal UI, stream handles, event formatting |
| **Context** | `agent/context.py`, `agent/truncation.py` | Token-based history compaction, oversized tool result truncation |
| **Model** | `model_resolution.py` | Provider/model resolution (Anthropic, OpenRouter) |
| **Observability** | `infra/otel_tracing.py` | OpenTelemetry span creation and configuration |
| **Utility** | `run_simple.py` | Convenience auto-approve wrapper for scripted runs |

## Key Design Decisions

### Single DBOS Queue
All work (chat, exec callbacks, future task types) flows through one priority
queue (`infra/work_queue.py`). Priority levels (`CRITICAL` to `IDLE`) control
ordering. This keeps the execution model simple and durable — DBOS handles
retries and persistence.

### Cryptographic Approval
Shell execution and filesystem operations (via `tools/exec_tool` and `tools/process_tool`)
require Ed25519-signed approval envelopes. Memory and subscription tools
operate on local SQLite databases and are wired without approval predicates.
The user unlocks their signing key at startup; the CLI prompts per-tool-call.
Approvals are stored in SQLite with nonce-based replay protection. This is a
real security boundary, not just a confirmation dialog.

### Flat Entry Point
`chat.py` is the single `main()`. It wires everything — env, backend, tools,
agent, DBOS, CLI — in one linear sequence. No framework magic, no plugin
discovery. You read `chat.py` and you see the full startup.

### Ephemeral Streams
`StreamHandle` instances live in-process only. They are NOT serialized or
persisted. Durability comes from the final `WorkItemOutput` written after
each turn. Streams are a convenience layer for real-time terminal display.

### Filesystem Skills
Skills are `.md` files in a directory. The agent discovers them at startup via
`SkillDirectory`. No registration, no imports — just drop a `SKILL.md` file.
Custom skills go in the workspace; shipped skills live in the repo `skills/`
directory.
