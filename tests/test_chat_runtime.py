"""Tests for runtime helpers split across chat modules."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from autopoiesis.prompts import compose_system_prompt


class TestComposeSystemPrompt:
    """Tests for compose_system_prompt."""

    def test_joins_fragments(self) -> None:
        result = compose_system_prompt(["A", "B", "C"])
        assert result == "A\n\nB\n\nC"

    def test_filters_empty_strings(self) -> None:
        result = compose_system_prompt(["A", "", "B", "", "C"])
        assert result == "A\n\nB\n\nC"

    def test_all_empty(self) -> None:
        assert compose_system_prompt(["", "", ""]) == ""

    def test_empty_sequence(self) -> None:
        assert compose_system_prompt([]) == ""

    def test_single_fragment(self) -> None:
        assert compose_system_prompt(["only"]) == "only"


class TestRequiredEnv:
    """Tests for required_env raising on missing vars."""

    def test_returns_value_when_set(self) -> None:
        from autopoiesis.agent.model_resolution import required_env

        with patch.dict(os.environ, {"TEST_VAR_XYZ": "hello"}):
            assert required_env("TEST_VAR_XYZ") == "hello"

    @pytest.mark.verifies("CHAT-V3")
    def test_raises_system_exit_when_missing(self) -> None:
        from autopoiesis.agent.model_resolution import required_env

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING_VAR_ABC", None)
            with pytest.raises(SystemExit, match="Missing required environment variable"):
                required_env("MISSING_VAR_ABC")

    def test_raises_on_empty_string(self) -> None:
        from autopoiesis.agent.model_resolution import required_env

        with (
            patch.dict(os.environ, {"EMPTY_VAR": ""}),
            pytest.raises(SystemExit, match="Missing required"),
        ):
            required_env("EMPTY_VAR")


class TestResolveWorkspaceRoot:
    """Tests for resolve_workspace_root with various env configs."""

    def test_absolute_path_used_directly(self, tmp_path: Path) -> None:
        from autopoiesis.tools.toolset_builder import resolve_workspace_root

        target = tmp_path / "workspace"
        with patch.dict(os.environ, {"AGENT_WORKSPACE_ROOT": str(target)}):
            result = resolve_workspace_root()
            assert result == target
            assert result.is_dir()

    def test_relative_path_resolved_from_module(self) -> None:
        from autopoiesis.tools.toolset_builder import resolve_workspace_root

        with patch.dict(os.environ, {"AGENT_WORKSPACE_ROOT": "data/test-ws"}):
            result = resolve_workspace_root()
            assert result.is_absolute()
            assert result.name == "test-ws"
            assert result.is_dir()

    def test_default_when_unset(self) -> None:
        from autopoiesis.tools.toolset_builder import resolve_workspace_root

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_WORKSPACE_ROOT", None)
            result = resolve_workspace_root()
            assert result.is_absolute()
            assert result.name == "agent-workspace"

    def test_creates_directory(self, tmp_path: Path) -> None:
        from autopoiesis.tools.toolset_builder import resolve_workspace_root

        target = tmp_path / "new" / "deep" / "ws"
        with patch.dict(os.environ, {"AGENT_WORKSPACE_ROOT": str(target)}):
            result = resolve_workspace_root()
            assert result.is_dir()

    def test_explicit_workspace_root_overrides_env(self, tmp_path: Path) -> None:
        from autopoiesis.tools.toolset_builder import resolve_workspace_root

        explicit = tmp_path / "agent" / "workspace"
        with patch.dict(os.environ, {"AGENT_WORKSPACE_ROOT": str(tmp_path / "ignored")}):
            result = resolve_workspace_root(explicit)
        assert result == explicit
        assert result.is_dir()


class TestBuildBackend:
    """Tests for backend creation with explicit workspace isolation."""

    def test_build_backend_uses_explicit_workspace(self, tmp_path: Path) -> None:
        from autopoiesis.tools.toolset_builder import build_backend

        workspace = tmp_path / "alpha" / "workspace"
        backend = build_backend(workspace)
        assert Path(str(backend.root_dir)).resolve() == workspace.resolve()


class TestBuildToolsets:
    """Tests for build_toolsets return type, toolset count, and system prompt."""

    @pytest.fixture(autouse=True)
    def _env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def test_returns_tuple(self) -> None:
        from autopoiesis.tools.toolset_builder import build_toolsets

        result = build_toolsets()
        assert isinstance(result, tuple)
        toolsets, system_prompt = result
        assert isinstance(toolsets, list)
        assert isinstance(system_prompt, str)
        assert len(system_prompt) > 0

    def test_toolset_count_without_knowledge(self) -> None:
        from autopoiesis.tools.toolset_builder import build_toolsets

        with patch.dict(os.environ, {"ENABLE_EXECUTE": ""}):
            toolsets, _ = build_toolsets()
            # console + skills + exec (hidden) = 3, wrapped
            min_toolsets = 3
            assert len(toolsets) >= min_toolsets

    def test_toolset_count_with_knowledge(self, tmp_path: Path) -> None:
        from autopoiesis.tools.toolset_builder import build_toolsets

        db_path = str(tmp_path / "knowledge.sqlite")
        from autopoiesis.store.knowledge import init_knowledge_index

        init_knowledge_index(db_path)
        toolsets, prompt = build_toolsets(knowledge_db_path=db_path)
        min_toolsets_with_knowledge = 4
        assert len(toolsets) >= min_toolsets_with_knowledge
        assert "knowledge" in prompt.lower()

    def test_exec_instructions_absent_when_disabled(self) -> None:
        with patch.dict(os.environ, {"ENABLE_EXECUTE": ""}):
            from autopoiesis.tools.toolset_builder import build_toolsets

            _, prompt = build_toolsets()
            assert "## Shell execution" not in prompt

    def test_exec_instructions_present_when_enabled(self) -> None:
        with patch.dict(os.environ, {"ENABLE_EXECUTE": "true"}):
            from autopoiesis.tools.toolset_builder import build_toolsets

            _, prompt = build_toolsets()
            assert "## Shell execution" in prompt


class TestBuildAgent:
    """Tests for build_agent with different providers."""

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def test_creates_anthropic_agent(self) -> None:
        from autopoiesis.agent.runtime import build_agent

        agent = build_agent("anthropic", "test", [], "You are helpful.")
        assert agent is not None
        assert agent.name == "test"

    def test_creates_openrouter_agent(self) -> None:
        from autopoiesis.agent.runtime import build_agent

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-key"}):
            agent = build_agent("openrouter", "or-test", [], "prompt")
            assert agent is not None
            assert agent.name == "or-test"

    def test_openrouter_missing_key_exits(self) -> None:
        from autopoiesis.agent.runtime import build_agent

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with pytest.raises(SystemExit, match="Missing required"):
                build_agent("openrouter", "test", [], "prompt")

    @pytest.mark.verifies("CHAT-V2")
    def test_unsupported_provider_exits(self) -> None:
        from autopoiesis.agent.runtime import build_agent

        with pytest.raises(SystemExit, match="Unsupported"):
            build_agent("unknown", "test", [], "prompt")

    def test_empty_instructions_not_coerced(self) -> None:
        """Empty list should stay as empty list, not become None."""
        from autopoiesis.agent.runtime import AgentOptions, build_agent

        agent = build_agent(
            "anthropic",
            "test",
            [],
            "prompt",
            options=AgentOptions(instructions=[]),
        )
        assert agent is not None

    def test_anthropic_missing_key_exits(self) -> None:
        from autopoiesis.agent.runtime import build_agent

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(SystemExit, match="Missing required"):
                build_agent("anthropic", "test", [], "prompt")


class TestPrepareToolsForProvider:
    """Tests for provider-specific tool preparation selection."""

    def test_openrouter_uses_strict_tool_preparation(self) -> None:
        from autopoiesis.agent.runtime import prepare_tools_for_provider
        from autopoiesis.tools.toolset_builder import strict_tool_definitions

        prepare = prepare_tools_for_provider("openrouter")
        assert prepare is strict_tool_definitions

    def test_anthropic_disables_tool_preparation(self) -> None:
        from autopoiesis.agent.runtime import prepare_tools_for_provider

        prepare = prepare_tools_for_provider("anthropic")
        assert prepare is None


class TestRuntimeRegistry:
    """Tests for lock-protected runtime registry injection and wrappers."""

    def test_get_before_set_raises(self) -> None:
        from autopoiesis.agent.runtime import RuntimeRegistry

        registry = RuntimeRegistry()
        with pytest.raises(RuntimeError, match="Runtime not initialised"):
            registry.get()

    def test_wrappers_use_injected_registry(self) -> None:
        from dataclasses import dataclass
        from typing import Any

        from autopoiesis.agent.runtime import (
            Runtime,
            RuntimeRegistry,
            get_runtime,
            reset_runtime,
            set_runtime,
            set_runtime_registry,
        )

        @dataclass
        class _FakeRuntime:
            agent_name: str = "default"
            agent: Any = None
            backend: Any = None
            history_db_path: str = ""
            knowledge_db_path: str = ""
            subscription_registry: Any = None
            approval_store: Any = None
            key_manager: Any = None
            tool_policy: Any = None
            approval_unlocked: bool = False
            shell_tier: str = "review"
            log_conversations: bool = False
            knowledge_root: Any = None
            conversation_log_retention_days: int = 0
            tmp_retention_days: int = 14
            tmp_max_size_mb: int = 500

        runtime = _FakeRuntime()
        injected = RuntimeRegistry()
        previous = set_runtime_registry(injected)
        try:
            set_runtime(cast(Runtime, runtime))
            assert get_runtime() is runtime
            reset_runtime()
            with pytest.raises(RuntimeError, match="Runtime not initialised"):
                get_runtime()
        finally:
            set_runtime_registry(previous)
