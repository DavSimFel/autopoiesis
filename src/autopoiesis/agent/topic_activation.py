"""Auto-activate topics when WorkItems carry a ``topic_ref``.

Extracted from ``worker.py`` to keep module size within arch constraints.

Dependencies: topics.topic_manager, tools.toolset_builder
Wired in: agent/worker.py → run_agent_step()
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def activate_topic_ref(topic_ref: str) -> None:
    """Attempt to transition a topic to ``in-progress`` status.

    Called before agent execution when a WorkItem carries a ``topic_ref``.
    Failures are logged but do not block execution.
    """
    try:
        from autopoiesis.tools.toolset_builder import resolve_workspace_root

        topics_dir = resolve_workspace_root() / "topics"
        if not topics_dir.is_dir():
            return
        from autopoiesis.topics.topic_manager import TopicRegistry, update_topic_status

        registry = TopicRegistry(topics_dir)
        topic = registry.get_topic(topic_ref)
        if topic is None:
            _log.debug("topic_ref '%s' not found; skipping activation", topic_ref)
            return
        if topic.status == "open":
            result = update_topic_status(registry, topic_ref, "in-progress")
            _log.info("topic_ref auto-activation: %s", result)
        else:
            _log.debug(
                "topic_ref '%s' status is '%s'; skipping activation",
                topic_ref,
                topic.status,
            )
    except Exception:
        _log.warning("Failed to auto-activate topic_ref '%s'", topic_ref, exc_info=True)
