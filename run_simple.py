"""Convenience wrapper for ``agent.run_sync()`` that auto-approves deferred tools.

``run_simple`` is intended for testing and quick scripting only.  Production
usage should go through the DBOS queue, which presents deferred tool requests
to a human for review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.messages import ModelMessage
from pydantic_ai.tools import DeferredToolApprovalResult, DeferredToolResults

from models import AgentDeps

logger = logging.getLogger(__name__)

AgentOutput = str | DeferredToolRequests

_MAX_APPROVAL_ROUNDS = 10


@dataclass(frozen=True)
class SimpleResult:
    """Return value from :func:`run_simple`."""

    text: str
    all_messages: list[ModelMessage]
    approval_rounds: int


def run_simple(
    agent: Agent[AgentDeps, str],
    prompt: str,
    deps: AgentDeps,
    *,
    message_history: list[ModelMessage] | None = None,
    max_rounds: int = _MAX_APPROVAL_ROUNDS,
) -> SimpleResult:
    """Run an agent synchronously, auto-approving any deferred tool requests.

    This loops up to *max_rounds* times.  Each iteration calls
    ``agent.run_sync`` with ``output_type=[str, DeferredToolRequests]``.
    When the result is a ``DeferredToolRequests``, every requested tool is
    approved and the agent is re-invoked with the approval results until a
    plain string is returned.

    Raises:
        RuntimeError: If the agent keeps requesting approvals beyond
            *max_rounds* iterations.
    """
    output_type: list[type[AgentOutput]] = [str, DeferredToolRequests]
    history = list(message_history) if message_history else []
    current_prompt: str | None = prompt
    deferred_results: DeferredToolResults | None = None

    for round_idx in range(max_rounds):
        result = agent.run_sync(
            current_prompt,
            deps=deps,
            message_history=history,
            output_type=output_type,
            deferred_tool_results=deferred_results,
        )
        if isinstance(result.output, str):
            return SimpleResult(
                text=result.output,
                all_messages=result.all_messages(),
                approval_rounds=round_idx,
            )

        logger.info(
            "Auto-approving %d deferred tool(s) (round %d)",
            len(result.output.approvals),
            round_idx + 1,
        )
        deferred_results = _auto_approve(result.output)
        history = result.all_messages()
        current_prompt = None

    raise RuntimeError(f"Agent did not produce a text response after {max_rounds} approval rounds.")


def _auto_approve(requests: DeferredToolRequests) -> DeferredToolResults:
    """Build a ``DeferredToolResults`` that approves every requested tool."""
    approvals: dict[str, DeferredToolApprovalResult | bool] = {}
    for call in requests.approvals:
        approvals[call.tool_call_id] = True
    return DeferredToolResults(approvals=approvals)
