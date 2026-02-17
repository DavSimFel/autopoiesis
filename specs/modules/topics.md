# Module: topics

## Purpose

Topic system for situational context injection — markdown files with YAML
frontmatter that define instructions, triggers, and subscriptions activated
on demand or by schedule.

## Status
- **Last updated:** 2026-02-16 (PR #136, Issue #129)
- **Source:** `src/autopoiesis/topics/topic_manager.py`, `src/autopoiesis/tools/topic_tools.py`, `src/autopoiesis/infra/topic_processor.py`

## Key Concepts
- **Topic** — A markdown file with YAML frontmatter defining a context bundle (instructions, triggers, subscriptions)
- **TopicRegistry** — In-memory registry that loads, activates, and deactivates topics
- **TopicTrigger** — Trigger definition (manual, cron, webhook) attached to a topic
- **Topic processor** — History processor that injects active topic instructions before each agent turn

## Architecture

| File | Responsibility |
|------|---------------|
| `src/autopoiesis/topics/topic_manager.py` | `TopicMeta`, `TopicTrigger`, `TopicRegistry` — loading, parsing, activation state, context building |
| `src/autopoiesis/tools/topic_tools.py` | PydanticAI tool definitions: `activate_topic`, `deactivate_topic`, `list_topics` |
| `src/autopoiesis/infra/topic_processor.py` | History processor that strips stale topic injections and inserts fresh context from active topics |

### Data Flow

1. `TopicRegistry` is initialised at startup and populated from topic directories
2. Agent tools allow runtime activation/deactivation of topics
3. Before each agent turn, `topic_processor` strips previous topic injections
   from history and injects current active topic context as a `ModelRequest`
   with metadata tag `active_topic_context`

## API Surface

### Agent Tools
- `activate_topic(topic_name)` — activate a topic for the current session
- `deactivate_topic(topic_name)` — deactivate a topic
- `list_topics()` — list all available topics with activation status

## Functions

### topic_manager.py
- `TopicRegistry.load(directories)` — scan directories for topic markdown files
- `TopicRegistry.activate(name)` / `deactivate(name)` — toggle topic state
- `build_topic_context(registry)` — render active topics into injectable context string

### tools/topic_tools.py
- `_register_tools(toolset, registry)` — register topic tools on a `FunctionToolset`
- `build_topic_toolset(registry)` — convenience builder returning toolset + instructions

### infra/topic_processor.py
- `is_topic_injection(msg)` — detect previous topic context injections
- `inject_topic_context(history, registry)` — strip old injections, prepend fresh context

## Invariants & Rules
- Topic files use `---` delimited YAML frontmatter
- Topic injections are tagged with `active_topic_context` metadata for reliable stripping
- The processor pattern mirrors `subscription_processor` — strip-then-inject per turn

## Dependencies
- `pydantic-ai-slim` (messages, toolsets)
- `pyyaml` (frontmatter parsing)
- Internal: `models.AgentDeps`

## Change Log
- 2026-02-16: Initial topic system — registry, tools, history processor (Issue #129, PR #136)
