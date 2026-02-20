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

## Queue Dispatch (Phase B — wired)

- `WorkItem.topic_ref: str | None` — optional topic reference for auto-activation
- `dispatch_workitem(item)` routes to per-agent DBOS queue by `agent_id` — **now wired into `enqueue()` and `enqueue_and_wait()` in `agent/worker.py`**
- `get_or_create_agent_queue(agent_id)` lazily creates per-agent queues

## Agent Spawning

`spawn_agent(template, task_name, parent)` creates ephemeral `AgentConfig`:
- Name: `"{template.name}-{task_name}"`
- Creates isolated workspace via `resolve_agent_workspace()`
- Inherits all config from template, sets `ephemeral=True`

## Centralized Name Validation (Phase B)

`agent.validation.validate_slug(name)` provides centralized validation for agent identifiers:
- Rejects empty strings, path traversal (`..`, `/`, `\`), names > 64 chars
- Used in: `spawner.py` (via `validate_agent_name`), `cli.py` (validates `--agent` arg), `config.py` (validates agent names from TOML)

## Isolation Guarantees

- Each agent gets isolated workspace under `~/.autopoiesis/agents/{name}/`
- Knowledge, topics, skills directories are per-agent
- DBOS system database is shared; `agent_id` on WorkItem provides logical isolation

## Conversation Logging Config (#189)

`AgentConfig` adds two fields controlling T2 reflection log storage:
- `log_conversations: bool` (default `True`) — when False, `worker.run_agent_step()` skips `append_turn()`.
- `conversation_log_retention_days: int` (default `30`) — files older than this are deleted by `rotate_logs()`.
Both fields can be set per-agent in `agents.toml` and inherit from `[defaults]`.

## Topic Auto-Activation (Phase B — wired)

When a WorkItem with `topic_ref` is dequeued, `run_agent_step()` calls
`_activate_topic_ref()` **before** agent execution. If the referenced topic
exists and has status `"open"`, it is transitioned to `"in-progress"` via
`update_topic_status()`. Non-open topics are skipped; missing topics are
logged and ignored. Failures do not block execution.
