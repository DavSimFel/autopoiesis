# Module: topics

## Purpose

Topic system for situational context injection — markdown files with YAML
frontmatter that define instructions, triggers, and subscriptions activated
on demand or by schedule. Topics support typed lifecycle management with
status transitions and owner assignment.

## Status
- **Last updated:** 2026-02-17 (Issue #150 Phase 1)
- **Source:** `src/autopoiesis/topics/topic_manager.py`, `src/autopoiesis/tools/topic_tools.py`, `src/autopoiesis/infra/topic_processor.py`

## Key Concepts
- **Topic** — A markdown file with YAML frontmatter defining a context bundle (instructions, triggers, subscriptions)
- **TopicRegistry** — In-memory registry that loads, activates, and deactivates topics
- **TopicTrigger** — Trigger definition (manual, cron, webhook) attached to a topic
- **Topic processor** — History processor that injects active topic instructions before each agent turn
- **TopicType** — Classification: general | task | project | goal | review | conversation
- **TopicStatus** — Lifecycle state: open | in-progress | review | done | archived
- **Owner** — Agent role string for routing

## Architecture

| File | Responsibility |
|------|---------------|
| `src/autopoiesis/topics/topic_manager.py` | `Topic`, `TopicTrigger`, `TopicRegistry` — loading, parsing, activation state, context building, lifecycle management |
| `src/autopoiesis/tools/topic_tools.py` | PydanticAI tool definitions: activate, deactivate, list, create, update status, set owner, query |
| `src/autopoiesis/infra/topic_processor.py` | History processor that strips stale topic injections and inserts fresh context from active topics |

### Data Flow

1. `TopicRegistry` is initialised at startup and populated from topic directories
2. Agent tools allow runtime activation/deactivation of topics
3. Before each agent turn, `topic_processor` strips previous topic injections
   from history and injects current active topic context as a `ModelRequest`
   with metadata tag `active_topic_context`
4. Lifecycle tools (`update_topic_status`, `set_topic_owner`, `create_topic`) modify
   frontmatter on disk with advisory locking (`fcntl.flock`) and reload the registry

## Topic Frontmatter Schema

Runtime parses **only** `type`, `status`, `owner` from frontmatter (plus existing
fields: triggers, subscriptions, approval, enabled, priority).

```yaml
---
type: task          # general | task | project | goal | review | conversation
status: open        # open | in-progress | review | done | archived
owner: planner      # agent role string
---
```

Missing fields default to: `type=general`, `status=None`, `owner=None`.

### Status Transitions by Type

| Type | Valid transitions |
|------|-----------------|
| general | No lifecycle (manual activate/deactivate only) |
| task | open → in-progress → review → done → archived |
| project | open → in-progress → done → archived |
| goal | open → in-progress → done |
| review | open → in-progress → done |
| conversation | open → archived |

## API Surface

### Agent Tools
- `activate_topic(name)` — activate a topic for the current session
- `deactivate_topic(name)` — deactivate a topic
- `list_topics()` — list all available topics with activation status
- `update_topic_status(name, status)` — transition a topic's lifecycle status
- `set_topic_owner(name, owner)` — assign an owner role to a topic
- `create_topic(name, type, body, owner)` — create a new topic file
- `query_topics(type, status, owner)` — filter topics by frontmatter fields

## Functions

### topic_manager.py
- `parse_topic(file_path)` — parse a topic file into a `Topic` object
- `TopicRegistry.__init__(topics_dir)` — scan directory for topic markdown files
- `TopicRegistry.activate(name)` / `deactivate(name)` — toggle topic state
- `build_topic_context(registry)` — render active topics into injectable context string
- `validate_status_transition(topic_type, current, new)` — check if transition is valid
- `update_topic_status(registry, name, status)` — validate and apply status transition
- `set_topic_owner(registry, name, owner)` — update owner in frontmatter
- `create_topic(registry, name, ...)` — create topic file with frontmatter
- `query_topics(registry, ...)` — filter topics by type/status/owner

### tools/topic_tools.py
- `_register_tools(toolset, registry)` — register all topic tools on a `FunctionToolset`
- `create_topic_toolset(registry)` — convenience builder returning toolset + instructions

### infra/topic_processor.py
- `is_topic_injection(msg)` — detect previous topic context injections
- `inject_topic_context(history, registry)` — strip old injections, prepend fresh context

## Invariants & Rules
- Topic files use `---` delimited YAML frontmatter
- Topic injections are tagged with `active_topic_context` metadata for reliable stripping
- The processor pattern mirrors `subscription_processor` — strip-then-inject per turn
- Frontmatter writes use `fcntl.flock()` advisory locking to prevent concurrent corruption
- `general` type topics have no status lifecycle — only manual activate/deactivate
- Missing frontmatter defaults to `type=general`, preserving full backward compatibility

## Dependencies
- `pydantic-ai-slim` (messages, toolsets)
- `pyyaml` (frontmatter parsing)
- Internal: `models.AgentDeps`

## Change Log
- 2026-02-17: Topic lifecycle schema — type/status/owner fields, status transitions, lifecycle tools, advisory locking (Issue #150 Phase 1)
- 2026-02-16: Initial topic system — registry, tools, history processor (Issue #129, PR #136)
