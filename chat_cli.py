"""Interactive CLI loop and approval handling."""

from __future__ import annotations

import sys
from uuid import uuid4

from approval_types import ApprovalVerificationError
from chat_approval import display_approval_requests, gather_approvals
from chat_runtime import get_runtime
from chat_worker import enqueue_and_wait
from models import WorkItem, WorkItemInput, WorkItemPriority, WorkItemType
from streaming import PrintStreamHandle, register_stream


def cli_chat_loop() -> None:
    """Interactive CLI chat loop backed by queue work items."""
    rt = get_runtime()
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
                register_stream(item.id, PrintStreamHandle())
                output = enqueue_and_wait(item)
                history_json = output.message_history_json

                if output.deferred_tool_requests_json is None:
                    break

                requests_payload = display_approval_requests(output.deferred_tool_requests_json)
                deferred_results_json = gather_approvals(
                    requests_payload,
                    approval_store=rt.approval_store,
                    key_manager=rt.key_manager,
                )
                prompt = None

        except ApprovalVerificationError as exc:
            print(f"Approval verification failed [{exc.code}]: {exc}", file=sys.stderr)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
