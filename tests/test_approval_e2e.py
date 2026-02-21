"""End-to-end approval flow tests across CLI and worker boundaries."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ToolCallPart
from pydantic_ai_backends import LocalBackend

import autopoiesis.agent.cli as chat_cli
import autopoiesis.agent.worker as chat_worker
from autopoiesis.infra.approval.keys import ApprovalKeyManager
from autopoiesis.infra.approval.policy import ToolPolicyRegistry
from autopoiesis.infra.approval.store import ApprovalStore
from autopoiesis.models import WorkItem, WorkItemOutput
from autopoiesis.store.history import init_history_store

_TOOL_CALL_ID = "call-1"
_EXPECTED_ENQUEUE_CALLS = 2


def _prompt_store() -> list[str | None]:
    return []


def _deferred_store() -> list[object | None]:
    return []


@dataclass
class _FakeRunResult:
    output: str | DeferredToolRequests
    _messages: list[Any]

    def all_messages(self) -> list[Any]:
        return self._messages


@dataclass
class _FakeAgent:
    name: str | None = "test-agent"
    prompts: list[str | None] = field(default_factory=_prompt_store)
    deferred_results: list[object | None] = field(default_factory=_deferred_store)

    def run_sync(
        self,
        prompt: str | None,
        *,
        deps: Any,
        message_history: list[Any],
        output_type: list[type[Any]],
        deferred_tool_results: object | None,
    ) -> _FakeRunResult:
        del deps, message_history, output_type
        self.prompts.append(prompt)
        self.deferred_results.append(deferred_tool_results)
        if deferred_tool_results is None:
            deferred = DeferredToolRequests(
                approvals=[
                    ToolCallPart(
                        tool_call_id=_TOOL_CALL_ID,
                        tool_name="execute",
                        args={"command": "echo hello"},
                    )
                ]
            )
            return _FakeRunResult(output=deferred, _messages=[])

        return _FakeRunResult(output="done", _messages=[])


@dataclass
class _FakeRuntime:
    agent: _FakeAgent
    backend: LocalBackend
    history_db_path: str
    approval_store: ApprovalStore
    key_manager: ApprovalKeyManager
    tool_policy: ToolPolicyRegistry
    agent_name: str = "default"
    approval_unlocked: bool = False
    log_conversations: bool = False
    knowledge_root: Path | None = None
    conversation_log_retention_days: int = 0
    tmp_retention_days: int = 14
    tmp_max_size_mb: int = 500


class _FakeHandle:
    approvals: ClassVar[list[tuple[str, str]]] = []

    def pause_display(self) -> None:
        return

    def resume_display(self) -> None:
        return

    def show_approval(self, summary: str, status: str) -> None:
        self.approvals.append((summary, status))


def _input_feeder(values: list[str]) -> Callable[[str], str]:
    iterator = iter(values)

    def _fake_input(_prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise AssertionError("Input requested more times than expected.") from exc

    return _fake_input


def _register_noop(_item_id: str, _handle: object) -> None:
    return


def test_cli_approval_flow_enqueue_reenqueue_and_consume(
    tmp_path: Path,
    approval_store: ApprovalStore,
    key_manager: ApprovalKeyManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_db = str(tmp_path / "history.sqlite")
    init_history_store(history_db)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    fake_agent = _FakeAgent()
    runtime = _FakeRuntime(
        agent=fake_agent,
        backend=LocalBackend(root_dir=str(workspace), enable_execute=False),
        history_db_path=history_db,
        approval_store=approval_store,
        key_manager=key_manager,
        tool_policy=ToolPolicyRegistry.default(),
        approval_unlocked=True,
    )

    captured_items: list[WorkItem] = []

    def _enqueue_and_wait(item: WorkItem) -> WorkItemOutput:
        captured_items.append(item)
        raw = chat_worker.run_agent_step(item.model_dump(mode="json"))
        return WorkItemOutput.model_validate(raw)

    _FakeHandle.approvals.clear()
    from autopoiesis.agent.runtime import RuntimeRegistry

    fake_registry = RuntimeRegistry()
    fake_registry.register("default", runtime)
    monkeypatch.setattr(chat_cli, "get_runtime", lambda: runtime)
    monkeypatch.setattr(chat_worker, "get_runtime_registry", lambda: fake_registry)
    monkeypatch.setattr(chat_cli, "RichStreamHandle", _FakeHandle)
    monkeypatch.setattr(chat_cli, "register_stream", _register_noop)
    monkeypatch.setattr(chat_cli, "enqueue_and_wait", _enqueue_and_wait)
    monkeypatch.setattr(chat_cli, "display_approval_requests", json.loads)
    monkeypatch.setattr("builtins.input", _input_feeder(["hello", "y", "exit"]))

    chat_cli.cli_chat_loop()

    assert len(captured_items) == _EXPECTED_ENQUEUE_CALLS
    assert captured_items[0].input.prompt == "hello"
    assert captured_items[0].input.deferred_tool_results_json is None
    assert captured_items[1].input.prompt is None
    assert captured_items[1].input.deferred_tool_results_json is not None
    assert (
        captured_items[1].input.approval_context_id == captured_items[0].input.approval_context_id
    )
    assert fake_agent.prompts == ["hello", None]
    assert fake_agent.deferred_results[0] is None
    assert fake_agent.deferred_results[1] is not None
    assert len(_FakeHandle.approvals) == 1
    assert _FakeHandle.approvals[0][1] == "done"
