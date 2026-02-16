"""Tests for topic discovery, parsing, activation, context injection, and tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from infra.topic_processor import inject_topic_context, is_topic_injection
from topic_manager import (
    TopicRegistry,
    build_topic_context,
    parse_topic,
)


@pytest.fixture()
def topics_dir(tmp_path: Path) -> Path:
    d = tmp_path / "topics"
    d.mkdir()
    return d


def _write_topic(topics_dir: Path, name: str, content: str) -> Path:
    p = topics_dir / f"{name}.md"
    p.write_text(content)
    return p


_SAMPLE_TOPIC = """\
---
triggers:
  - type: manual
  - type: cron
    schedule: "*/5 * * * *"
subscriptions:
  - inbox_state
  - contacts
approval: auto
enabled: true
priority: normal
---

# Email Triage

## Instructions

Classify emails as urgent, actionable, or informational.
"""

_DISABLED_TOPIC = """\
---
triggers:
  - type: manual
enabled: false
priority: low
---

# Disabled Topic

Do nothing.
"""

_MINIMAL_TOPIC = """\
---
triggers: []
---

# Minimal

Just instructions, no extras.
"""


class TestParseTopic:
    def test_parse_frontmatter_and_body(self, topics_dir: Path) -> None:
        path = _write_topic(topics_dir, "email-triage", _SAMPLE_TOPIC)
        topic = parse_topic(path)
        assert topic.name == "email-triage"
        assert len(topic.triggers) == 2  # noqa: PLR2004
        assert topic.triggers[0].type == "manual"
        assert topic.triggers[1].type == "cron"
        assert topic.triggers[1].schedule == "*/5 * * * *"
        assert topic.subscriptions == ("inbox_state", "contacts")
        assert topic.approval == "auto"
        assert topic.enabled is True
        assert topic.priority == "normal"
        assert "Classify emails" in topic.instructions

    def test_parse_disabled_topic(self, topics_dir: Path) -> None:
        path = _write_topic(topics_dir, "disabled", _DISABLED_TOPIC)
        topic = parse_topic(path)
        assert topic.enabled is False
        assert topic.priority == "low"

    def test_parse_minimal_topic(self, topics_dir: Path) -> None:
        path = _write_topic(topics_dir, "minimal", _MINIMAL_TOPIC)
        topic = parse_topic(path)
        assert topic.name == "minimal"
        assert topic.triggers == ()
        assert topic.subscriptions == ()
        assert topic.approval == "auto"
        assert topic.enabled is True

    def test_no_frontmatter(self, topics_dir: Path) -> None:
        path = _write_topic(topics_dir, "plain", "# Just markdown\n\nNo frontmatter here.")
        topic = parse_topic(path)
        assert topic.name == "plain"
        assert topic.triggers == ()
        assert "Just markdown" in topic.instructions


class TestTopicRegistry:
    def test_discovery(self, topics_dir: Path) -> None:
        _write_topic(topics_dir, "alpha", _SAMPLE_TOPIC)
        _write_topic(topics_dir, "beta", _MINIMAL_TOPIC)
        registry = TopicRegistry(topics_dir)
        names = [t.name for t in registry.list_topics()]
        assert "alpha" in names
        assert "beta" in names

    def test_empty_dir(self, topics_dir: Path) -> None:
        registry = TopicRegistry(topics_dir)
        assert registry.list_topics() == []

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        registry = TopicRegistry(tmp_path / "nope")
        assert registry.list_topics() == []

    def test_activate_deactivate(self, topics_dir: Path) -> None:
        _write_topic(topics_dir, "test", _SAMPLE_TOPIC)
        registry = TopicRegistry(topics_dir)

        assert not registry.is_active("test")
        assert registry.activate("test")
        assert registry.is_active("test")

        # Double activate returns False
        assert not registry.activate("test")

        assert registry.deactivate("test")
        assert not registry.is_active("test")

        # Double deactivate returns False
        assert not registry.deactivate("test")

    def test_activate_nonexistent(self, topics_dir: Path) -> None:
        registry = TopicRegistry(topics_dir)
        assert not registry.activate("nope")

    def test_activate_disabled(self, topics_dir: Path) -> None:
        _write_topic(topics_dir, "disabled", _DISABLED_TOPIC)
        registry = TopicRegistry(topics_dir)
        assert not registry.activate("disabled")

    def test_get_active_topics(self, topics_dir: Path) -> None:
        _write_topic(topics_dir, "a", _SAMPLE_TOPIC)
        _write_topic(topics_dir, "b", _MINIMAL_TOPIC)
        registry = TopicRegistry(topics_dir)
        registry.activate("a")
        registry.activate("b")
        active = registry.get_active_topics()
        names = {t.name for t in active}
        assert names == {"a", "b"}

    def test_get_cron_topics(self, topics_dir: Path) -> None:
        _write_topic(topics_dir, "cron-topic", _SAMPLE_TOPIC)
        _write_topic(topics_dir, "manual-only", _MINIMAL_TOPIC)
        registry = TopicRegistry(topics_dir)
        cron = registry.get_cron_topics()
        assert len(cron) == 1
        assert cron[0].name == "cron-topic"

    def test_reload(self, topics_dir: Path) -> None:
        registry = TopicRegistry(topics_dir)
        assert len(registry.list_topics()) == 0
        _write_topic(topics_dir, "new", _MINIMAL_TOPIC)
        registry.reload()
        assert len(registry.list_topics()) == 1


class TestBuildTopicContext:
    def test_no_active_topics(self, topics_dir: Path) -> None:
        registry = TopicRegistry(topics_dir)
        assert build_topic_context(registry) is None

    def test_single_active(self, topics_dir: Path) -> None:
        _write_topic(topics_dir, "review", _SAMPLE_TOPIC)
        registry = TopicRegistry(topics_dir)
        registry.activate("review")
        ctx = build_topic_context(registry)
        assert ctx is not None
        assert "review" in ctx.instructions
        assert "inbox_state" in ctx.subscription_names

    def test_multiple_active(self, topics_dir: Path) -> None:
        _write_topic(topics_dir, "a", _SAMPLE_TOPIC)
        _write_topic(topics_dir, "b", _MINIMAL_TOPIC)
        registry = TopicRegistry(topics_dir)
        registry.activate("a")
        registry.activate("b")
        ctx = build_topic_context(registry)
        assert ctx is not None
        assert "a" in ctx.instructions
        assert "b" in ctx.instructions


class TestTopicContextInjection:
    @staticmethod
    def _make_messages() -> list[ModelMessage]:
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content="Hello")]),
            ModelRequest(parts=[UserPromptPart(content="How are you?")]),
        ]
        return msgs

    def test_no_active_topics_passthrough(self, topics_dir: Path) -> None:
        registry = TopicRegistry(topics_dir)
        msgs = self._make_messages()
        result = inject_topic_context(msgs, registry)
        assert len(result) == 2  # noqa: PLR2004

    def test_active_topic_injected(self, topics_dir: Path) -> None:
        _write_topic(topics_dir, "review", _SAMPLE_TOPIC)
        registry = TopicRegistry(topics_dir)
        registry.activate("review")
        msgs = self._make_messages()
        result = inject_topic_context(msgs, registry)
        assert len(result) == 3  # noqa: PLR2004
        # The injection should be before the last message
        injected = result[1]
        assert is_topic_injection(injected)

    def test_old_injection_stripped(self, topics_dir: Path) -> None:
        _write_topic(topics_dir, "review", _SAMPLE_TOPIC)
        registry = TopicRegistry(topics_dir)
        registry.activate("review")
        msgs = self._make_messages()
        # Inject once
        result = inject_topic_context(msgs, registry)
        assert len(result) == 3  # noqa: PLR2004
        # Inject again — old injection should be replaced, not duplicated
        result2 = inject_topic_context(result, registry)
        assert len(result2) == 3  # noqa: PLR2004

    def test_is_topic_injection_false_for_normal(self) -> None:
        msg = ModelRequest(parts=[UserPromptPart(content="hi")])
        assert not is_topic_injection(msg)
