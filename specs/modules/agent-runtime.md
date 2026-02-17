# Agent Runtime Specification

**Module:** `agent.config`, `agent.spawner`, `infra.work_queue` (dispatch extensions)
**Issue:** #146 Phase B

## Overview

The agent runtime provides multi-agent support through configuration-driven
agent definitions, queue-based dispatch, and ephemeral agent spawning.

## Agent Config

Each agent is described by an `AgentConfig` frozen dataclass:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique identifier (e.g. `"planner"`, `"executor-fix-123"`) |
| `role` | `str` | One of `"proxy"`, `"planner"`, `"executor"` |
| `model` | `str` | LLM model identifier |
| `tools` | `list[str]` | Allowed tool names |
| `shell_tier` | `str` | `"free"` / `"review"` / `"approve"` |
| `system_prompt` | `Path` | Relative path to system prompt markdown |
| `ephemeral` | `bool` | Whether agent is destroyed after task completion |
| `parent` | `str \| None` | Parent agent name (for spawned agents) |

### TOML Configuration

Agents are defined in an `agents.toml` file with a `[defaults]` section
and per-agent `[agents.<name>]` sections. Defaults are merged into each
agent entry. Missing config file → single `"default"` agent (backward compat).

**Loader:** `load_agent_configs(config_path: Path) -> dict[str, AgentConfig]`

### CLI Integration

- `--config agents.toml` flag or `AUTOPOIESIS_AGENTS_CONFIG` env var
- Without config: single default agent, fully backward compatible

## Queue Dispatch

- `WorkItem.topic_ref: str | None` — optional topic reference for auto-activation
- `dispatch_workitem(item)` routes to per-agent DBOS queue by `agent_id`
- `get_or_create_agent_queue(agent_id)` lazily creates per-agent queues

## Agent Spawning

`spawn_agent(template, task_name, parent)` creates ephemeral `AgentConfig`:
- Name: `"{template.name}-{task_name}"`
- Creates isolated workspace via `resolve_agent_workspace()`
- Inherits all config from template, sets `ephemeral=True`

## Isolation Guarantees

- Each agent gets isolated workspace under `~/.autopoiesis/agents/{name}/`
- Knowledge, topics, skills directories are per-agent
- DBOS system database is shared; `agent_id` on WorkItem provides logical isolation

## Topic Auto-Activation

When a WorkItem with `topic_ref` is dequeued, the worker resolves the topic
in the agent's workspace and activates it via `TopicRegistry.activate()`.
