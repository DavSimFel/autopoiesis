"""Tests for runtime helpers split across chat modules."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from prompts import compose_system_prompt


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
        from model_resolution import required_env

        with patch.dict(os.environ, {"TEST_VAR_XYZ": "hello"}):
            assert required_env("TEST_VAR_XYZ") == "hello"

    def test_raises_system_exit_when_missing(self) -> None:
        from model_resolution import required_env

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING_VAR_ABC", None)
            with pytest.raises(SystemExit, match="Missing required environment variable"):
                required_env("MISSING_VAR_ABC")

    def test_raises_on_empty_string(self) -> None:
        from model_resolution import required_env

        with (
            patch.dict(os.environ, {"EMPTY_VAR": ""}),
            pytest.raises(SystemExit, match="Missing required"),
        ):
            required_env("EMPTY_VAR")


class TestResolveWorkspaceRoot:
    """Tests for resolve_workspace_root with various env configs."""

    def test_absolute_path_used_directly(self, tmp_path: Path) -> None:
        from toolset_builder import resolve_workspace_root

        target = tmp_path / "workspace"
        with patch.dict(os.environ, {"AGENT_WORKSPACE_ROOT": str(target)}):
            result = resolve_workspace_root()
            assert result == target
            assert result.is_dir()

    def test_relative_path_resolved_from_module(self) -> None:
        from toolset_builder import resolve_workspace_root

        with patch.dict(os.environ, {"AGENT_WORKSPACE_ROOT": "data/test-ws"}):
            result = resolve_workspace_root()
            assert result.is_absolute()
            assert result.name == "test-ws"
            assert result.is_dir()

    def test_default_when_unset(self) -> None:
        from toolset_builder import resolve_workspace_root

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_WORKSPACE_ROOT", None)
            result = resolve_workspace_root()
            assert result.is_absolute()
            assert result.name == "agent-workspace"

    def test_creates_directory(self, tmp_path: Path) -> None:
        from toolset_builder import resolve_workspace_root

        target = tmp_path / "new" / "deep" / "ws"
        with patch.dict(os.environ, {"AGENT_WORKSPACE_ROOT": str(target)}):
            result = resolve_workspace_root()
            assert result.is_dir()


class TestBuildToolsets:
    """Tests for build_toolsets return type, toolset count, and system prompt."""

    @pytest.fixture(autouse=True)
    def _env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def test_returns_tuple(self) -> None:
        from toolset_builder import build_toolsets

        result = build_toolsets()
        assert isinstance(result, tuple)
        toolsets, system_prompt = result
        assert isinstance(toolsets, list)
        assert isinstance(system_prompt, str)
        assert len(system_prompt) > 0

    def test_toolset_count_without_memory(self) -> None:
        from toolset_builder import build_toolsets

        with patch.dict(os.environ, {"ENABLE_EXECUTE": ""}):
            toolsets, _ = build_toolsets()
            # console + skills + exec (hidden) = 3, wrapped
            min_toolsets = 3
            assert len(toolsets) >= min_toolsets

    def test_toolset_count_with_memory(self, tmp_path: Path) -> None:
        from toolset_builder import build_toolsets

        db_path = str(tmp_path / "mem.sqlite")
        from memory_store import init_memory_store

        init_memory_store(db_path)
        toolsets, prompt = build_toolsets(memory_db_path=db_path)
        min_toolsets_with_memory = 4
        assert len(toolsets) >= min_toolsets_with_memory
        assert "memory" in prompt.lower()

    def test_exec_instructions_absent_when_disabled(self) -> None:
        with patch.dict(os.environ, {"ENABLE_EXECUTE": ""}):
            from toolset_builder import build_toolsets

            _, prompt = build_toolsets()
            assert "## Shell execution" not in prompt

    def test_exec_instructions_present_when_enabled(self) -> None:
        with patch.dict(os.environ, {"ENABLE_EXECUTE": "true"}):
            from toolset_builder import build_toolsets

            _, prompt = build_toolsets()
            assert "## Shell execution" in prompt


class TestBuildAgent:
    """Tests for build_agent with different providers."""

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def test_creates_anthropic_agent(self) -> None:
        from chat_runtime import build_agent

        agent = build_agent("anthropic", "test", [], "You are helpful.")
        assert agent is not None
        assert agent.name == "test"

    def test_creates_openrouter_agent(self) -> None:
        from chat_runtime import build_agent

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-key"}):
            agent = build_agent("openrouter", "or-test", [], "prompt")
            assert agent is not None
            assert agent.name == "or-test"

    def test_openrouter_missing_key_exits(self) -> None:
        from chat_runtime import build_agent

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with pytest.raises(SystemExit, match="Missing required"):
                build_agent("openrouter", "test", [], "prompt")

    def test_unsupported_provider_exits(self) -> None:
        from chat_runtime import build_agent

        with pytest.raises(SystemExit, match="Unsupported"):
            build_agent("unknown", "test", [], "prompt")

    def test_empty_instructions_not_coerced(self) -> None:
        """Empty list should stay as empty list, not become None."""
        from chat_runtime import AgentOptions, build_agent

        agent = build_agent(
            "anthropic",
            "test",
            [],
            "prompt",
            options=AgentOptions(instructions=[]),
        )
        assert agent is not None

    def test_anthropic_missing_key_exits(self) -> None:
        from chat_runtime import build_agent

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(SystemExit, match="Missing required"):
                build_agent("anthropic", "test", [], "prompt")
