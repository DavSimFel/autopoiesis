"""Topic loader and activation manager.

Topics are markdown files with YAML frontmatter that define situational
context bundles — instructions, triggers, and subscriptions that get
injected into the agent context when activated.
"""

from __future__ import annotations

import fcntl
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml

logger = logging.getLogger(__name__)

TriggerType = Literal["manual", "cron", "webhook"]
ApprovalMode = Literal["auto", "prompt", "deny"]
TopicPriority = Literal["critical", "high", "normal", "low"]
TopicType = Literal["general", "task", "project", "goal", "review", "conversation"]
TopicStatus = Literal["open", "in-progress", "review", "done", "archived"]

_FRONTMATTER_DELIMITER = "---"
MAX_ACTIVE_TOPICS = 5
MAX_TOPIC_CONTEXT_BYTES = 10_240  # 10 KB

VALID_TOPIC_TYPES = frozenset({"general", "task", "project", "goal", "review", "conversation"})
VALID_TOPIC_STATUSES = frozenset({"open", "in-progress", "review", "done", "archived"})

# Valid status transitions per topic type.  ``general`` has NO lifecycle.
STATUS_TRANSITIONS: dict[str, dict[str, list[str]]] = {
    "task": {
        "open": ["in-progress"],
        "in-progress": ["review"],
        "review": ["done"],
        "done": ["archived"],
    },
    "project": {
        "open": ["in-progress"],
        "in-progress": ["done"],
        "done": ["archived"],
    },
    "goal": {
        "open": ["in-progress"],
        "in-progress": ["done"],
    },
    "review": {
        "open": ["in-progress"],
        "in-progress": ["done"],
    },
    "conversation": {
        "open": ["archived"],
    },
}


@dataclass(frozen=True)
class TopicTrigger:
    """A single trigger definition for a topic."""

    type: TriggerType
    source: str | None = None
    event: str | None = None
    schedule: str | None = None


@dataclass(frozen=True)
class Topic:
    """A parsed topic with metadata and instructions."""

    name: str
    instructions: str
    triggers: tuple[TopicTrigger, ...]
    subscriptions: tuple[str, ...]
    approval: ApprovalMode
    enabled: bool
    priority: TopicPriority
    file_path: Path
    type: TopicType = "general"
    status: TopicStatus | None = None
    owner: str | None = None


def _parse_trigger(raw: dict[str, str]) -> TopicTrigger:
    """Parse a single trigger dict from frontmatter."""
    trigger_type = raw.get("type", "manual")
    if trigger_type not in ("manual", "cron", "webhook"):
        trigger_type = "manual"
    return TopicTrigger(
        type=trigger_type,  # type: ignore[arg-type]
        source=raw.get("source"),
        event=raw.get("event"),
        schedule=raw.get("schedule"),
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown file into YAML frontmatter dict and body text.

    Returns ``({}, full_text)`` when no valid frontmatter is found.
    """
    stripped = text.lstrip()
    if not stripped.startswith(_FRONTMATTER_DELIMITER):
        return {}, text

    # Find second delimiter
    first_end = stripped.index("\n") + 1
    rest = stripped[first_end:]
    try:
        second_idx = rest.index(f"\n{_FRONTMATTER_DELIMITER}")
    except ValueError:
        return {}, text

    yaml_text = rest[:second_idx]
    body_start = second_idx + len(f"\n{_FRONTMATTER_DELIMITER}")
    body = rest[body_start:].lstrip("\n")

    try:
        parsed: object = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return {}, text
    if not isinstance(parsed, dict):
        return {}, text
    result = cast(dict[str, Any], parsed)
    return result, body


def parse_topic(file_path: Path) -> Topic:
    """Parse a single topic file into a Topic object."""
    text = file_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)

    triggers: list[TopicTrigger] = []
    raw_triggers: object = meta.get("triggers")
    if isinstance(raw_triggers, list):
        for trigger_obj in cast(list[Any], raw_triggers):
            if isinstance(trigger_obj, dict):
                triggers.append(_parse_trigger(cast(dict[str, str], trigger_obj)))

    subs: list[str] = []
    raw_subs: object = meta.get("subscriptions")
    if isinstance(raw_subs, list):
        subs = [str(s) for s in cast(list[Any], raw_subs)]

    raw_approval: str = str(meta.get("approval", "auto"))
    approval: ApprovalMode = raw_approval if raw_approval in ("auto", "prompt", "deny") else "auto"  # type: ignore[assignment]

    raw_priority: str = str(meta.get("priority", "normal"))
    priority: TopicPriority = (
        raw_priority  # type: ignore[assignment]
        if raw_priority in ("critical", "high", "normal", "low")
        else "normal"
    )

    raw_type: str = str(meta.get("type", "general"))
    topic_type: TopicType = raw_type if raw_type in VALID_TOPIC_TYPES else "general"  # type: ignore[assignment]

    raw_status: object = meta.get("status")
    topic_status: TopicStatus | None = None
    if isinstance(raw_status, str) and raw_status in VALID_TOPIC_STATUSES:
        topic_status = raw_status  # type: ignore[assignment]

    raw_owner: object = meta.get("owner")
    topic_owner: str | None = str(raw_owner) if raw_owner is not None else None

    name = file_path.stem

    return Topic(
        name=name,
        instructions=body,
        triggers=tuple(triggers),
        subscriptions=tuple(subs),
        approval=approval,
        enabled=bool(meta.get("enabled", True)),
        priority=priority,
        file_path=file_path,
        type=topic_type,
        status=topic_status,
        owner=topic_owner,
    )


class TopicRegistry:
    """Discovers, loads, and manages topic activation state."""

    def __init__(self, topics_dir: Path) -> None:
        self._topics_dir = topics_dir
        self._topics: dict[str, Topic] = {}
        self._active: set[str] = set()
        self._load_topics()

    def _load_topics(self) -> None:
        """Scan the topics directory and parse all .md files."""
        self._topics.clear()
        if not self._topics_dir.is_dir():
            logger.debug("Topics directory not found: %s", self._topics_dir)
            return
        for md_file in sorted(self._topics_dir.glob("*.md")):
            try:
                topic = parse_topic(md_file)
                self._topics[topic.name] = topic
            except Exception:
                logger.warning("Failed to parse topic file: %s", md_file, exc_info=True)

    @property
    def topics_dir(self) -> Path:
        """Return the topics directory path."""
        return self._topics_dir

    def reload(self) -> None:
        """Re-scan and reload all topics from disk."""
        self._load_topics()

    def list_topics(self) -> list[Topic]:
        """Return all discovered topics."""
        return list(self._topics.values())

    def get_topic(self, name: str) -> Topic | None:
        """Return a topic by name, or None if not found."""
        return self._topics.get(name)

    def get_active_topics(self) -> list[Topic]:
        """Return all currently active topics."""
        return [self._topics[n] for n in self._active if n in self._topics]

    def activate(self, name: str) -> bool:
        """Activate a topic by name. Returns True if newly activated."""
        topic = self._topics.get(name)
        if topic is None:
            return False
        if not topic.enabled:
            return False
        if name in self._active:
            return False
        if len(self._active) >= MAX_ACTIVE_TOPICS:
            msg = (
                f"Cannot activate '{name}': max concurrent topics "
                f"({MAX_ACTIVE_TOPICS}) reached. Deactivate one first."
            )
            raise ValueError(msg)
        self._active.add(name)
        return True

    def deactivate(self, name: str) -> bool:
        """Deactivate a topic by name. Returns True if was active."""
        if name not in self._active:
            return False
        self._active.discard(name)
        return True

    def is_active(self, name: str) -> bool:
        """Check if a topic is currently active."""
        return name in self._active

    def get_cron_topics(self) -> list[Topic]:
        """Return enabled topics that have cron triggers."""
        result: list[Topic] = []
        for topic in self._topics.values():
            if not topic.enabled:
                continue
            if any(t.type == "cron" for t in topic.triggers):
                result.append(topic)
        return result


@dataclass
class TopicContext:
    """Aggregated context from all active topics for injection into prompts."""

    instructions: str
    subscription_names: list[str]


def build_topic_context(registry: TopicRegistry) -> TopicContext | None:
    """Build aggregated context from all active topics.

    Returns None when no topics are active.
    """
    active = registry.get_active_topics()
    if not active:
        return None

    # Sort by priority so higher-priority topics get included first
    priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    active.sort(key=lambda t: priority_order.get(t.priority, 2))

    parts: list[str] = []
    all_subs: list[str] = []
    total_size = 0

    for topic in active:
        header = f"## Active Topic: {topic.name} (priority: {topic.priority})\n"
        section = header + "\n\n" + topic.instructions
        section_size = len(section.encode("utf-8"))
        if total_size + section_size > MAX_TOPIC_CONTEXT_BYTES:
            remaining = MAX_TOPIC_CONTEXT_BYTES - total_size
            if remaining > 0:
                parts.append(section[:remaining] + "\n[...truncated]")
            break
        total_size += section_size
        parts.append(header)
        parts.append(topic.instructions)
        all_subs.extend(topic.subscriptions)

    instructions = "\n\n".join(parts)
    return TopicContext(instructions=instructions, subscription_names=all_subs)


# ---------------------------------------------------------------------------
# Frontmatter write helpers (with advisory locking)
# ---------------------------------------------------------------------------


def _write_frontmatter(file_path: Path, meta: dict[str, Any], body: str) -> None:
    """Write frontmatter + body to *file_path* with advisory locking."""
    content = _FRONTMATTER_DELIMITER + "\n"
    content += yaml.dump(meta, default_flow_style=False, sort_keys=True)
    content += _FRONTMATTER_DELIMITER + "\n"
    if body:
        content += "\n" + body

    with file_path.open("w", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.write(content)
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _update_frontmatter_field(
    file_path: Path,
    field: str,
    value: str,
) -> dict[str, Any]:
    """Read a topic file, update one frontmatter field, write back.

    Returns the updated metadata dict.
    """
    text = file_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    meta[field] = value
    _write_frontmatter(file_path, meta, body)
    return meta


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------


def validate_status_transition(
    topic_type: str,
    current_status: str | None,
    new_status: str,
) -> str | None:
    """Return an error message if the transition is invalid, else ``None``."""
    if topic_type == "general":
        return "Topics of type 'general' have no lifecycle status transitions."
    transitions = STATUS_TRANSITIONS.get(topic_type)
    if transitions is None:
        return f"Unknown topic type '{topic_type}'."
    if new_status not in VALID_TOPIC_STATUSES:
        return f"Invalid status '{new_status}'."

    error: str | None = None
    if current_status is None:
        if new_status != "open":
            error = (
                f"Topic has no status yet; first transition must be to 'open', got '{new_status}'."
            )
    elif new_status not in transitions.get(current_status, []):
        allowed = transitions.get(current_status, [])
        error = (
            f"Cannot transition from '{current_status}' to '{new_status}' "
            f"for type '{topic_type}'. Allowed: {allowed}."
        )
    return error


def update_topic_status(registry: TopicRegistry, name: str, status: str) -> str:
    """Validate and apply a status transition for a topic."""
    topic = registry.get_topic(name)
    if topic is None:
        return f"Topic '{name}' not found."
    error = validate_status_transition(topic.type, topic.status, status)
    if error is not None:
        return error
    _update_frontmatter_field(topic.file_path, "status", status)
    registry.reload()
    return f"Topic '{name}' status updated to '{status}'."


def set_topic_owner(registry: TopicRegistry, name: str, owner: str) -> str:
    """Set the owner field on a topic."""
    topic = registry.get_topic(name)
    if topic is None:
        return f"Topic '{name}' not found."
    _update_frontmatter_field(topic.file_path, "owner", owner)
    registry.reload()
    return f"Topic '{name}' owner set to '{owner}'."


def create_topic(
    registry: TopicRegistry,
    name: str,
    *,
    type: str = "general",
    body: str = "",
    owner: str | None = None,
) -> str:
    """Create a new topic file with frontmatter."""
    if type not in VALID_TOPIC_TYPES:
        return f"Invalid topic type '{type}'."
    file_path = registry.topics_dir / f"{name}.md"
    if file_path.exists():
        return f"Topic '{name}' already exists."
    meta: dict[str, Any] = {"type": type}
    if owner is not None:
        meta["owner"] = owner
    _write_frontmatter(file_path, meta, body)
    registry.reload()
    return f"Topic '{name}' created."


def query_topics(
    registry: TopicRegistry,
    *,
    type: str | None = None,
    status: str | None = None,
    owner: str | None = None,
) -> list[Topic]:
    """Filter topics by type, status, and/or owner."""
    results: list[Topic] = []
    for topic in registry.list_topics():
        if type is not None and topic.type != type:
            continue
        if status is not None and topic.status != status:
            continue
        if owner is not None and topic.owner != owner:
            continue
        results.append(topic)
    return results
