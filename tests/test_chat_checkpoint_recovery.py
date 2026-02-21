"""Integration tests for chat checkpoint recovery behavior."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from _pytest.monkeypatch import MonkeyPatch

import autopoiesis.agent.worker as chat_worker
from autopoiesis.models import WorkItem, WorkItemInput, WorkItemPriority, WorkItemType
from autopoiesis.store.history import init_history_store, load_checkpoint, save_checkpoint


@dataclass
class _FakeRunResult:
    output: str

    def all_messages(self) -> list[Any]:
        return []


@dataclass
class _FakeAgent:
    name: str | None = "test-agent"
    captured_message_history: list[Any] | None = None

    def run_sync(
        self,
        prompt: str,
        *,
        deps: Any,
        message_history: list[Any],
        output_type: list[type[Any]],
        deferred_tool_results: Any,
    ) -> _FakeRunResult:
        self.captured_message_history = message_history
        return _FakeRunResult(output="ok")


@dataclass
class _FakeRuntime:
    agent: Any
    backend: Any
    history_db_path: str
    agent_name: str = "default"
    approval_store: Any = None
    key_manager: Any = None
    approval_unlocked: bool = False
    tool_policy: Any = None
    log_conversations: bool = False
    knowledge_root: Path | None = None
    conversation_log_retention_days: int = 0
    tmp_retention_days: int = 14
    tmp_max_size_mb: int = 500


def _fake_deserialize_history(history_json: str | None) -> list[str]:
    if history_json is None:
        return []
    return [f"decoded:{history_json}"]


def _fake_serialize_history(messages: list[Any]) -> str:
    del messages
    return "serialized-history"


def test_run_agent_step_prefers_checkpoint_history_and_clears_checkpoint(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    history_db = tmp_path / "history.sqlite"
    init_history_store(str(history_db))
    save_checkpoint(str(history_db), "work-item-1", "checkpoint-history", 2)

    fake_agent = _FakeAgent()
    fake_backend = type("FakeBackend", (), {"root_dir": str(tmp_path)})()
    runtime = _FakeRuntime(
        agent=cast(Any, fake_agent),
        backend=cast(Any, fake_backend),
        history_db_path=str(history_db),
    )
    from autopoiesis.agent.runtime import RuntimeRegistry

    fake_registry = RuntimeRegistry()
    fake_registry.register(runtime)
    monkeypatch.setattr(chat_worker, "get_runtime_registry", lambda: fake_registry)
    monkeypatch.setattr(chat_worker, "_deserialize_history", _fake_deserialize_history)
    monkeypatch.setattr(chat_worker, "_serialize_history", _fake_serialize_history)

    item = WorkItem(
        id="work-item-1",
        type=WorkItemType.CHAT,
        priority=WorkItemPriority.CRITICAL,
        input=WorkItemInput(prompt="Hello", message_history_json="stale-history"),
    )

    output = chat_worker.run_agent_step(item.model_dump(mode="json"))

    assert fake_agent.captured_message_history == ["decoded:checkpoint-history"]
    assert output["text"] == "ok"
    assert load_checkpoint(str(history_db), "work-item-1") is None
