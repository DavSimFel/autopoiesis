"""Tests for worker error wrapping across the DBOS workflow boundary."""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai_backends import LocalBackend

import agent.worker as chat_worker
from models import WorkItem, WorkItemInput, WorkItemPriority, WorkItemType
from store.history import init_history_store


@dataclass
class _FailingAgent:
    name: str | None = "test-agent"

    def run_sync(
        self,
        prompt: str | None,
        *,
        deps: Any,
        message_history: list[Any],
        output_type: list[type[Any]],
        deferred_tool_results: Any,
    ) -> Any:
        del prompt, deps, message_history, output_type, deferred_tool_results
        raise ModelHTTPError(
            status_code=400,
            model_name="anthropic:claude-3-5-sonnet-latest",
            body={"error": {"message": "Schema is too complex for compilation."}},
        )


@dataclass
class _FakeRuntime:
    agent: Any
    backend: LocalBackend
    history_db_path: str
    approval_store: Any = None
    key_manager: Any = None
    tool_policy: Any = None


def test_run_agent_step_wraps_model_http_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_agent_step should raise RuntimeError rather than ModelHTTPError."""
    history_db = tmp_path / "history.sqlite"
    init_history_store(str(history_db))
    runtime = _FakeRuntime(
        agent=_FailingAgent(),
        backend=LocalBackend(root_dir=str(tmp_path), enable_execute=False),
        history_db_path=str(history_db),
    )
    monkeypatch.setattr(chat_worker, "get_runtime", lambda: runtime)

    item = WorkItem(
        id="work-item-error",
        type=WorkItemType.CHAT,
        priority=WorkItemPriority.CRITICAL,
        input=WorkItemInput(prompt="hello"),
    )

    with pytest.raises(RuntimeError, match="ModelHTTPError") as exc_info:
        chat_worker.run_agent_step(item.model_dump(mode="json"))

    restored = pickle.loads(pickle.dumps(exc_info.value))
    assert "ModelHTTPError" in str(restored)
