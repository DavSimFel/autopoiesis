"""Interactive CLI loop and approval handling.

Dependencies: agent.runtime, agent.worker, approval.chat_approval,
    approval.types, display.streaming, models
Wired in: chat.py → main()
"""

from __future__ import annotations

import sys
from typing import Any
from uuid import uuid4

from agent.runtime import get_runtime
from agent.worker import enqueue_and_wait
from approval.chat_approval import display_approval_requests, gather_approvals
from approval.types import ApprovalVerificationError
from display.streaming import ChannelStatus, RichStreamHandle, register_stream
from models import WorkItem, WorkItemInput, WorkItemPriority, WorkItemType


def _collapse_approval(
    handle: RichStreamHandle,
    payload: dict[str, Any],
    *,
    approved: bool,
) -> None:
    """Create and immediately collapse an approval channel in the display."""
    requests = payload.get("requests", [])
    tool_names = ", ".join(str(r.get("tool_name", "?")) for r in requests)
    status: ChannelStatus = "done" if approved else "error"
    label = "approved" if approved else "denied"
    summary = f"{tool_names} — {label}"
    handle.show_approval(summary, status)


def _run_turn(
    user_input: str,
    history_json: str | None,
) -> str | None:
    """Execute one user turn, handling deferred approval loops.

    Returns updated history JSON after the turn completes.
    """
    rt = get_runtime()
    prompt: str | None = user_input
    deferred_results_json: str | None = None
    approval_context_id = uuid4().hex

    while True:
        item = WorkItem(
            type=WorkItemType.CHAT,
            priority=WorkItemPriority.CRITICAL,
            input=WorkItemInput(
                prompt=prompt,
                message_history_json=history_json,
                deferred_tool_results_json=deferred_results_json,
                approval_context_id=approval_context_id,
            ),
        )
        handle = RichStreamHandle()
        register_stream(item.id, handle)
        output = enqueue_and_wait(item)
        history_json = output.message_history_json

        if output.deferred_tool_requests_json is None:
            break

        handle.pause_display()
        requests_payload = display_approval_requests(output.deferred_tool_requests_json)
        try:
            deferred_results_json = gather_approvals(
                requests_payload,
                approval_store=rt.approval_store,
                key_manager=rt.key_manager,
            )
            _collapse_approval(handle, requests_payload, approved=True)
        except (EOFError, KeyboardInterrupt):
            _collapse_approval(handle, requests_payload, approved=False)
            raise
        finally:
            handle.resume_display()
        prompt = None

    return history_json


def cli_chat_loop() -> None:
    """Interactive CLI chat loop backed by queue work items."""
    history_json: str | None = None
    print("Autopoiesis CLI Chat (type 'exit' to quit)")
    print("---")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Goodbye.")
            break

        try:
            history_json = _run_turn(user_input, history_json)
        except ApprovalVerificationError as exc:
            print(f"Approval verification failed [{exc.code}]: {exc}", file=sys.stderr)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
