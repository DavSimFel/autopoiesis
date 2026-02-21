"""Tests for issue #200: propagate selected agent identity into runtime and WorkItem routing.

Acceptance criteria:
- ``--agent <name>`` and ``AUTOPOIESIS_AGENT`` select active runtime identity consistently.
- Interactive ``WorkItem`` creation sets ``agent_id`` to the selected agent (no implicit
  default routing for non-default agents).
- Runtime ``agent_name`` field reflects the selected agent identity.
- ``_resolve_startup_config`` no longer exposes an ``agent_name`` component sourced from
  ``DBOS_AGENT_NAME`` -- the name travels through the ``_initialize_runtime`` parameter.
- Two sessions with different agent names enqueue work on different agent queues.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _MinimalRuntime:
    """Minimal duck-typed runtime for unit tests that don't need full wiring."""

    agent_name: str
    agent: Any = None
    backend: Any = None
    history_db_path: str = ":memory:"
    knowledge_db_path: str = ":memory:"
    subscription_registry: Any = None
    approval_store: Any = None
    key_manager: Any = None
    tool_policy: Any = None
    approval_unlocked: bool = False
    log_conversations: bool = False
    knowledge_root: Path | None = None
    conversation_log_retention_days: int = 0
    tmp_retention_days: int = 14
    tmp_max_size_mb: int = 500


# ---------------------------------------------------------------------------
# 1. Runtime.agent_name field exists and is propagated
# ---------------------------------------------------------------------------


class TestRuntimeAgentNameField:
    """Runtime dataclass must expose agent_name."""

    def test_runtime_has_agent_name_field(self) -> None:
        from autopoiesis.agent.runtime import Runtime

        fields = {f.name for f in Runtime.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        assert "agent_name" in fields, "Runtime must have an agent_name field"

    def test_runtime_agent_name_stored(self) -> None:
        """agent_name passed to Runtime is retrievable."""
        rt = _MinimalRuntime(agent_name="my-agent")
        assert rt.agent_name == "my-agent"

    def test_non_default_agent_name_preserved(self) -> None:
        rt = _MinimalRuntime(agent_name="prod-worker")
        assert rt.agent_name == "prod-worker"


# ---------------------------------------------------------------------------
# 2. _resolve_startup_config no longer returns agent_name from DBOS_AGENT_NAME
# ---------------------------------------------------------------------------


class TestResolveStartupConfigSignature:
    """_resolve_startup_config must return (provider, system_database_url) only."""

    def test_returns_two_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("DBOS_SYSTEM_DATABASE_URL", raising=False)

        from autopoiesis.cli import _resolve_startup_config  # type: ignore[reportPrivateUsage]

        result = _resolve_startup_config()
        assert len(result) == 2, (
            "_resolve_startup_config should return (provider, system_database_url) -- "
            "agent_name must come from the CLI/env resolution path, not DBOS_AGENT_NAME"
        )

    @pytest.mark.verifies("CHAT-V6")
    def test_dbos_agent_name_not_in_return(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even if DBOS_AGENT_NAME is set it must not leak into the return value."""
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DBOS_AGENT_NAME", "should-not-appear")

        from autopoiesis.cli import _resolve_startup_config  # type: ignore[reportPrivateUsage]

        result = _resolve_startup_config()
        assert "should-not-appear" not in result


# ---------------------------------------------------------------------------
# 3. _initialize_runtime accepts agent_name as a parameter
# ---------------------------------------------------------------------------


class TestInitializeRuntimeSignature:
    """_initialize_runtime must accept agent_name as an explicit positional arg."""

    def test_agent_name_is_required_parameter(self) -> None:
        from autopoiesis.cli import initialize_runtime

        sig = inspect.signature(initialize_runtime)
        params = list(sig.parameters.keys())
        assert "agent_name" in params, (
            "_initialize_runtime must accept agent_name so the CLI-resolved "
            "identity is passed rather than DBOS_AGENT_NAME"
        )

    def test_agent_name_is_positional_not_keyword_only(self) -> None:
        from autopoiesis.cli import initialize_runtime

        sig = inspect.signature(initialize_runtime)
        p = sig.parameters["agent_name"]
        assert p.kind not in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.VAR_KEYWORD,
        ), "agent_name should be a regular positional parameter"


# ---------------------------------------------------------------------------
# 4. WorkItem created in _run_turn carries the runtime's agent_name
# ---------------------------------------------------------------------------


class TestRunTurnSetsAgentId:
    """_run_turn must set WorkItem.agent_id from rt.agent_name."""

    @pytest.mark.verifies("CHAT-V1")
    def test_workitem_uses_runtime_agent_name(self, tmp_path: Path) -> None:
        """WorkItem.agent_id must equal the runtime's agent_name, not 'default'."""
        from autopoiesis.models import WorkItem, WorkItemOutput

        captured: list[WorkItem] = []

        def _fake_enqueue_and_wait(item: WorkItem) -> WorkItemOutput:
            captured.append(item)
            return WorkItemOutput(text="ok", message_history_json=None)

        fake_rt = _MinimalRuntime(agent_name="staging")

        import autopoiesis.agent.cli as agent_cli

        with (
            patch.object(agent_cli, "get_runtime", return_value=fake_rt),
            patch.object(agent_cli, "enqueue_and_wait", side_effect=_fake_enqueue_and_wait),
            patch.object(agent_cli, "RichStreamHandle", MagicMock),
            patch.object(agent_cli, "register_stream", MagicMock()),
        ):
            agent_cli._run_turn("hello", None)  # type: ignore[reportPrivateUsage]

        assert captured, "enqueue_and_wait was never called"
        assert captured[0].agent_id == "staging", (
            f"Expected agent_id='staging', got '{captured[0].agent_id}'. "
            "WorkItem must propagate the runtime agent_name."
        )

    def test_default_agent_name_still_works(self) -> None:
        """When agent_name is 'default', agent_id should be 'default'."""
        from autopoiesis.models import WorkItem, WorkItemOutput

        captured: list[WorkItem] = []

        def _fake_enqueue_and_wait(item: WorkItem) -> WorkItemOutput:
            captured.append(item)
            return WorkItemOutput(text="ok", message_history_json=None)

        fake_rt = _MinimalRuntime(agent_name="default")

        import autopoiesis.agent.cli as agent_cli

        with (
            patch.object(agent_cli, "get_runtime", return_value=fake_rt),
            patch.object(agent_cli, "enqueue_and_wait", side_effect=_fake_enqueue_and_wait),
            patch.object(agent_cli, "RichStreamHandle", MagicMock),
            patch.object(agent_cli, "register_stream", MagicMock()),
        ):
            agent_cli._run_turn("hello", None)  # type: ignore[reportPrivateUsage]

        assert captured[0].agent_id == "default"


# ---------------------------------------------------------------------------
# 5. Worker uses rt.agent_name (not DBOS_AGENT_NAME fallback) for approval scope
# ---------------------------------------------------------------------------


class TestWorkerUsesRuntimeAgentName:
    """run_agent_step must derive agent_name from rt.agent_name, not env var."""

    def test_approval_scope_uses_runtime_agent_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build_approval_scope receives rt.agent_name, not DBOS_AGENT_NAME."""
        monkeypatch.setenv("DBOS_AGENT_NAME", "stale-name-from-env")

        captured_scope_names: list[str] = []

        @dataclass
        class _FakeAgent:
            name: str | None = "test-agent"

            def run_sync(self, *args: Any, **kwargs: Any) -> Any:
                result = MagicMock()
                result.output = "done"
                result.all_messages.return_value = []
                return result

        fake_rt = _MinimalRuntime(
            agent_name="runtime-agent",
            agent=_FakeAgent(),
            backend=MagicMock(root_dir=str(tmp_path)),
        )

        from autopoiesis.agent import worker

        original_build_scope = worker.build_approval_scope

        def _capturing_build_scope(approval_context_id: str, backend: Any, agent_name: str) -> Any:
            captured_scope_names.append(agent_name)
            return original_build_scope(approval_context_id, backend, agent_name)

        from autopoiesis.store.history import init_history_store

        history_db = str(tmp_path / "history.sqlite")
        init_history_store(history_db)
        fake_rt.history_db_path = history_db

        from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hi"),
            agent_id="runtime-agent",
        )

        from autopoiesis.agent.runtime import RuntimeRegistry

        fake_registry = RuntimeRegistry()
        fake_registry.register(fake_rt)
        with (
            patch.object(worker, "get_runtime_registry", return_value=fake_registry),
            patch.object(worker, "build_approval_scope", side_effect=_capturing_build_scope),
        ):
            worker.run_agent_step(item.model_dump(mode="json"))

        assert captured_scope_names, "build_approval_scope was not called"
        assert captured_scope_names[0] == "runtime-agent", (
            f"Expected agent_name='runtime-agent' but got '{captured_scope_names[0]}'. "
            "Worker must use rt.agent_name, not DBOS_AGENT_NAME."
        )


# ---------------------------------------------------------------------------
# 6. Two sessions with different agent names use different queues
# ---------------------------------------------------------------------------


class TestTwoAgentsDifferentQueues:
    """Running two sessions with different agent names enqueues on different queues."""

    def test_different_agents_different_queue_names(self) -> None:
        from autopoiesis.infra.work_queue import dispatch_workitem
        from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

        item_alpha = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hi from alpha"),
            agent_id="alpha",
        )
        item_beta = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hi from beta"),
            agent_id="beta",
        )

        queue_alpha = dispatch_workitem(item_alpha)
        queue_beta = dispatch_workitem(item_beta)

        assert queue_alpha is not queue_beta, (
            "Agents 'alpha' and 'beta' must use different queue objects"
        )
        assert queue_alpha.name != queue_beta.name, (
            "Queue names must differ across different agent identities"
        )

    def test_same_agent_same_queue(self) -> None:
        from autopoiesis.infra.work_queue import dispatch_workitem
        from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

        item1 = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="turn 1"),
            agent_id="consistent-agent",
        )
        item2 = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="turn 2"),
            agent_id="consistent-agent",
        )

        assert dispatch_workitem(item1) is dispatch_workitem(item2), (
            "The same agent_id must always resolve to the same queue object"
        )

    def test_non_default_agent_not_on_default_queue(self) -> None:
        from autopoiesis.infra.work_queue import dispatch_workitem, work_queue
        from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hi"),
            agent_id="special-agent",
        )
        q = dispatch_workitem(item)
        assert q is not work_queue, (
            "A non-default agent must not be routed to the default work_queue"
        )


# ---------------------------------------------------------------------------
# 7. CLI arg / env resolution correctly flows into resolve_agent_name
# ---------------------------------------------------------------------------


class TestAgentNameResolutionFlow:
    """The resolved agent name from --agent / AUTOPOIESIS_AGENT flows end-to-end."""

    def test_cli_flag_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOPOIESIS_AGENT", "from-env")
        from autopoiesis.agent.workspace import resolve_agent_name

        assert resolve_agent_name("from-cli") == "from-cli"

    def test_env_used_when_no_cli_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOPOIESIS_AGENT", "from-env")
        from autopoiesis.agent.workspace import resolve_agent_name

        assert resolve_agent_name(None) == "from-env"

    @pytest.mark.verifies("CHAT-V7")
    def test_default_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTOPOIESIS_AGENT", raising=False)
        from autopoiesis.agent.workspace import resolve_agent_name

        assert resolve_agent_name(None) == "default"

    def test_dbos_agent_name_does_not_influence_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DBOS_AGENT_NAME must not be consulted during agent name resolution."""
        monkeypatch.setenv("DBOS_AGENT_NAME", "stale-dbos-name")
        monkeypatch.delenv("AUTOPOIESIS_AGENT", raising=False)
        from autopoiesis.agent.workspace import resolve_agent_name

        result = resolve_agent_name(None)
        assert result == "default", (
            f"DBOS_AGENT_NAME should not be consulted; expected 'default', got '{result}'"
        )
