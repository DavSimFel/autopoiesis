"""Auto-activate topics when WorkItems carry a ``topic_ref``.

Extracted from ``worker.py`` to keep module size within arch constraints.

Phase 2 addition: when a topic is activated, the associated skill's MCP tools
are also enabled on the FastMCP server via :class:`SkillActivator`.  By
convention a topic named ``"github"`` maps to a skill also named ``"github"``.

Dependencies: topics.topic_manager, tools.toolset_builder, server.mcp_server
Wired in: agent/worker.py → run_agent_step()
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def _try_activate_skill(topic_ref: str) -> None:
    """Enable the skill's MCP tools that correspond to *topic_ref*, if any.

    By convention the topic name maps to the skill directory name.  Failures
    are silently logged — missing skill providers are expected and normal.
    """
    try:
        from autopoiesis.server.mcp_server import skill_activator

        if skill_activator is None:
            return
        activated = skill_activator.activate_skill_for_topic(topic_ref)
        if activated:
            _log.info("MCP skill tools activated for topic_ref '%s'", topic_ref)
        else:
            _log.debug("No MCP skill server for topic_ref '%s'", topic_ref)
    except Exception:
        _log.warning(
            "Failed to activate MCP skill for topic_ref '%s'",
            topic_ref,
            exc_info=True,
        )


def activate_topic_ref(topic_ref: str) -> None:
    """Attempt to transition a topic to ``in-progress`` status.

    Also enables the associated skill's MCP tools (Phase 2 lazy loading).
    Called before agent execution when a WorkItem carries a ``topic_ref``.
    Failures are logged but do not block execution.
    """
    try:
        from autopoiesis.tools.toolset_builder import resolve_workspace_root

        topics_dir = resolve_workspace_root() / "topics"
        if not topics_dir.is_dir():
            return
        from autopoiesis.topics.topic_manager import (
            TopicRegistry,
            update_topic_status,
        )

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

    # Phase 2: also enable the skill's MCP tools when the topic fires.
    _try_activate_skill(topic_ref)
