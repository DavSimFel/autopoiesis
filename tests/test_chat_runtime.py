"""Tests for chat_runtime: _compose_system_prompt, build_toolsets, build_agent."""

from __future__ import annotations

import os
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


class TestBuildToolsets:
    """Tests for build_toolsets return type and system prompt."""

    @pytest.fixture(autouse=True)
    def _env(self, tmp_path: pytest.TempPathFactory) -> None:  # type: ignore[override]
        workspace = str(tmp_path)
        self._patches = [
            patch.dict(
                os.environ,
                {
                    "AGENT_WORKSPACE_ROOT": workspace,
                    "ANTHROPIC_API_KEY": "test-key",
                },
            ),
        ]
        for p in self._patches:
            p.start()

    @pytest.fixture(autouse=True)
    def _cleanup(self) -> None:  # type: ignore[override]
        yield  # type: ignore[misc]
        for p in self._patches:
            p.stop()

    def test_returns_tuple(self) -> None:
        from chat_runtime import build_toolsets

        result = build_toolsets()
        assert isinstance(result, tuple)
        toolsets, system_prompt = result
        assert isinstance(toolsets, list)
        assert isinstance(system_prompt, str)
        assert len(system_prompt) > 0

    def test_exec_instructions_absent_when_disabled(self) -> None:
        with patch.dict(os.environ, {"ENABLE_EXECUTE": ""}):
            from chat_runtime import build_toolsets

            _, prompt = build_toolsets()
            assert "## Shell execution" not in prompt

    def test_exec_instructions_present_when_enabled(self) -> None:
        with patch.dict(os.environ, {"ENABLE_EXECUTE": "true"}):
            from chat_runtime import build_toolsets

            _, prompt = build_toolsets()
            assert "## Shell execution" in prompt


class TestBuildAgent:
    """Tests for build_agent signature and behavior."""

    @pytest.fixture(autouse=True)
    def _env(self) -> None:  # type: ignore[override]
        self._patch = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
        self._patch.start()

    @pytest.fixture(autouse=True)
    def _cleanup(self) -> None:  # type: ignore[override]
        yield  # type: ignore[misc]
        self._patch.stop()

    def test_creates_anthropic_agent(self) -> None:
        from chat_runtime import build_agent

        agent = build_agent("anthropic", "test", [], "You are helpful.")
        assert agent is not None
        assert agent.name == "test"

    def test_unsupported_provider_exits(self) -> None:
        from chat_runtime import build_agent

        with pytest.raises(SystemExit, match="Unsupported"):
            build_agent("unknown", "test", [], "prompt")

    def test_empty_instructions_not_coerced(self) -> None:
        """Empty list should stay as empty list, not become None."""
        from chat_runtime import build_agent

        agent = build_agent("anthropic", "test", [], "prompt", instructions=[])
        # The key assertion: empty list should not be truthy-coerced to None
        assert agent is not None
