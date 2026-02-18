# Architecture

## 10-Second Overview

Autopoiesis is a durable CLI chat agent built on **PydanticAI** + **DBOS**.
User messages become work items on a priority queue. A DBOS worker executes
each item by running a PydanticAI agent with shell, knowledge, topic, subscription,
and skill tools. Cryptographic approval gates dangerous operations.
Responses stream back to a Rich terminal UI.

## System Diagram

```
┌──────────────────────────────────────────────────────────────┐
│  src/autopoiesis/cli.py (entrypoint)                         │
│  ┌────────────┐  ┌───────────────┐  ┌──────────────────┐    │
│  │ agent/cli  │→│ agent/worker  │→│ agent/runtime    │    │
│  │ (REPL)     │  │ (DBOS queue)  │  │ (agent builder)  │    │
│  └─────┬──────┘  └──────┬────────┘  └───────┬──────────┘    │
│        │                │                    │               │
│        ▼                ▼                    ▼               │
│  ┌───────────┐  ┌──────────────┐  ┌──────────────────┐      │
│  │ display/  │  │ approval/    │  │ toolset_builder  │      │
│  │ streaming │  │ (crypto gate)│  │ (tool wiring)    │      │
│  └───────────┘  └──────────────┘  └────────┬─────────┘      │
│                                            │                │
│                 ┌──────────┬───────────────┼────────┐       │
│                 ▼          ▼               ▼        ▼       │
│          ┌──────────┐ ┌────────┐ ┌──────────┐ ┌────────┐   │
│          │ exec +   │ │ know-  │ │ topics/  │ │ skills │   │
│          │ process  │ │ ledge  │ │ subs     │ │        │   │
│          └──────────┘ └────────┘ └──────────┘ └────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## Tool Inventory

| Tool | Module | Approval | Purpose |
|------|--------|----------|---------|
| **exec** | `tools/exec_tool.py`, `tools/process_tool.py` | Yes | Shell execution, PTY sessions, process inspection/control with tier checks |
| **knowledge** | `tools/knowledge_tools.py` | No | File-based knowledge search and retrieval |
| **topics** | `tools/topic_tools.py` | No | Topic lifecycle: activate, deactivate, status transitions |
| **subscriptions** | `tools/subscription_tools.py` | No | File/topic subscriptions for reactive context injection |
| **skills** | `skills.py` | No | Filesystem skill discovery, progressive disclosure |
| **skillmaker** | `skillmaker_tools.py` | No | Validate and lint skill files |

### Shell Command Classification

Execution tools classify commands into security tiers via `infra/command_classifier.py`:

| Tier | Approval | Examples |
|------|----------|---------|
| **FREE** | None | `ls`, `cat`, `git status`, `find` |
| **REVIEW** | User reviews | `git commit`, `pip install`, `python -c ...`, `tmux new -d ...` |
| **APPROVE** | Explicit sign | `rm`, `curl \| sh`, write operations |
| **BLOCK** | Denied | `sudo`, commands with `&&` chaining dangerous ops |

## Agent Tiers

The WorkItem queue supports a three-tier agent hierarchy:

| Tier | Role | Description |
|------|------|-------------|
| **T1** | Human | The user. Issues commands, approves operations. |
| **T2** | Planner / Orchestrator | Decomposes tasks, creates WorkItems for T3 agents. Routes via topics. |
| **T3** | Workers | Execute scoped tasks (code, review, research). Isolated workspaces. |

Currently T1→T3 (direct CLI) is the primary path. T2 orchestration and T3 multi-agent flows are being built (see WorkItem 3-Tier Flow in tests).

## Multi-Agent Coordination

### WorkItems

Every unit of work is a `WorkItem` on a DBOS priority queue (`infra/work_queue.py`). Priority levels: `CRITICAL` → `HIGH` → `NORMAL` → `LOW` → `IDLE`.

### Agent Isolation

Each agent gets its own workspace, history, and tool context. Agents cannot see each other's state. Isolation is enforced at the runtime level.

### Topic Routing

Topics enable inter-agent communication:
- An agent activates a topic → subscribes to updates
- WorkItems can be routed to topic owners
- Owner-based triggers fire when relevant work arrives

## Data Flow: One Chat Turn

1. User types at `>` prompt → `agent/cli.py`
2. Wrapped in `WorkItem(type=CHAT, priority=CRITICAL)`
3. Enqueued on DBOS work queue
4. Worker dispatches → `run_agent_step()` builds agent with tools
5. PydanticAI streams response → Rich terminal UI
6. Tool calls requiring approval → `DeferredToolRequests` → CLI prompts user
7. Completed `WorkItemOutput` (text + history) returns to CLI

## Key Design Decisions

### Single DBOS Queue
All work flows through one priority queue. DBOS handles retries and persistence. Simple and durable.

### Cryptographic Approval
Shell and file operations require Ed25519-signed envelopes with nonce-based replay protection. This is a real security boundary, not a confirmation dialog.

### Flat Entry Point
`src/autopoiesis/cli.py` is the single `main()` entrypoint. No framework magic, no plugin discovery. Read it and see the full startup.

### File-First Philosophy
- **Specs** are markdown files in `specs/modules/`
- **Skills** are markdown files in `skills/`
- **Knowledge** is searchable text in SQLite FTS5
- **Configuration** is `.env` + minimal frontmatter
- Everything version-controlled in git

### Plan System (Upcoming)
Contract-based plan execution with hard verification. Plans define expected outcomes; the system verifies them programmatically, not by asking the LLM "did you do it?". See `docs/research/plan-system-design.md`.

## Package Responsibilities

| Cluster | Key Files | Purpose |
|---------|-----------|---------|
| **Entry & CLI** | `src/autopoiesis/cli.py`, `agent/cli.py` | Env loading, DBOS bootstrap, REPL |
| **Agent Runtime** | `agent/runtime.py`, `agent/worker.py`, `infra/work_queue.py` | Agent construction, queue worker, work items |
| **Tool Wiring** | `toolset_builder.py`, `tools/toolset_wrappers.py`, `prompts.py` | Assembles toolsets, composes system prompt |
| **Execution** | `tools/exec_tool.py`, `tools/process_tool.py`, `infra/command_classifier.py`, `tools/tier_enforcement.py` | Shell/process execution with command classification and approval gating |
| **Knowledge** | `tools/knowledge_tools.py`, `store/knowledge.py` | File-backed persistent knowledge store |
| **Skills** | `skills.py`, `skillmaker_tools.py` | Filesystem skill discovery, validation |
| **Subscriptions** | `tools/subscription_tools.py`, `store/subscriptions.py`, `infra/subscription_processor.py` | Reactive context injection |
| **Approval** | `approval/` | Ed25519 signing, envelope storage, policy |
| **Persistence** | `store/history.py`, `db.py` | SQLite checkpoint store, shared DB helpers |
| **Display** | `display/` | Rich terminal UI, streaming |
| **Context** | `agent/context.py`, `agent/truncation.py` | History compaction, result truncation |
| **Observability** | `infra/otel_tracing.py` | OpenTelemetry spans |
