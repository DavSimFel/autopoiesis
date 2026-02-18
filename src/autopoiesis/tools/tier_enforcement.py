"""Command tier enforcement shared by shell execution tools.

Dependencies: infra.command_classifier
Wired in: tools/exec_tool.py
"""

from __future__ import annotations

from pydantic_ai.messages import ToolReturn

from autopoiesis.infra.command_classifier import Tier, classify


def enforce_tier(command: str, approval_unlocked: bool) -> ToolReturn | None:
    """Check command tier and return a blocked ToolReturn if not permitted.

    Returns ``None`` if the command is allowed, otherwise a ``ToolReturn``
    with blocked metadata.
    """
    tier = classify(command)
    if tier is Tier.BLOCK:
        return ToolReturn(
            return_value=f"Blocked: command classified as {tier.value}.",
            metadata={"blocked": True, "tier": tier.value},
        )
    if not approval_unlocked and tier is not Tier.FREE:
        return ToolReturn(
            return_value=(
                f"Approval required: command classified as {tier.value}. "
                "Unlock approval keys or use Docker backend."
            ),
            metadata={"blocked": True, "tier": tier.value},
        )
    return None
