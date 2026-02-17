# Agent Workspace — Spec

## Purpose

Provide per-agent directory isolation so multiple agent identities can run
without sharing mutable state (keys, data, knowledge, memory).

## Core Types

### `AgentPaths` (frozen dataclass)

| Field       | Path                                     |
|-------------|------------------------------------------|
| `root`      | `~/.autopoiesis/agents/{name}/`          |
| `workspace` | `root/workspace/`                        |
| `memory`    | `root/workspace/memory/`                 |
| `skills`    | `root/workspace/skills/`                 |
| `knowledge` | `root/workspace/knowledge/`              |
| `tmp`       | `root/workspace/tmp/`                    |
| `data`      | `root/data/`                             |
| `keys`      | `root/keys/`                             |

### `resolve_agent_name(cli_agent=None) -> str`

Resolution order: CLI flag → `AUTOPOIESIS_AGENT` env var → `"default"`.

### `resolve_agent_workspace(agent_name=None) -> AgentPaths`

Builds all paths from `AUTOPOIESIS_HOME` (default `~/.autopoiesis`) and agent name.

## CLI Integration

- `--agent <name>` flag on main CLI parser
- Env var `AUTOPOIESIS_AGENT` as fallback
- Default: `"default"` — backward compatible

## WorkItem Extension

- `agent_id: str = "default"` field on `WorkItem` model

## Wiring

`cli.py → main()` resolves `AgentPaths` and passes `agent_paths.root` as
`base_dir` to `ApprovalStore.from_env()` and `ApprovalKeyManager.from_env()`.
