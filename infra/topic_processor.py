"""History processor that injects active topic instructions before each turn.

Similar to subscription_processor, this strips old topic injections and
inserts fresh ones based on currently active topics.
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    UserPromptPart,
)

from topic_manager import TopicRegistry, build_topic_context

_TOPIC_TAG = "active_topic_context"


def is_topic_injection(msg: ModelMessage) -> bool:
    """Return True if *msg* is a previous topic context injection."""
    if not isinstance(msg, ModelRequest):
        return False
    meta = msg.metadata
    if meta is None:
        return False
    return _TOPIC_TAG in meta


def inject_topic_context(
    messages: list[ModelMessage],
    registry: TopicRegistry,
) -> list[ModelMessage]:
    """History processor: inject active topic instructions.

    1. Strip old topic injection messages
    2. Build context from active topics
    3. Insert before the last message
    """
    cleaned = [m for m in messages if not is_topic_injection(m)]

    context = build_topic_context(registry)
    if context is None:
        return cleaned

    topic_msg = ModelRequest(
        parts=[
            UserPromptPart(
                content=(
                    "[Active Topic Context]\n\n"
                    "The following topic instructions are active. "
                    "Follow them for this session.\n\n"
                    f"{context.instructions}"
                ),
            ),
        ],
        metadata={_TOPIC_TAG: True},
    )

    insert_pos = max(0, len(cleaned) - 1)
    cleaned.insert(insert_pos, topic_msg)
    return cleaned
