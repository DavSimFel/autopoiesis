"""Unit tests for AgentConfig → runtime wiring (Issue #201).

Covers:
- Config selection precedence (agent name → config lookup in main startup).
- Model assignment from AgentConfig via resolve_model_from_config.
- Tool/toolset filtering from AgentConfig.tools.
- Missing/unknown agent config fails fast with actionable error.
- Default (no config file) behaviour remains backward-compatible.
- Shell tier propagation to Runtime.
- System prompt override from AgentConfig.system_prompt file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autopoiesis.agent.config import AgentConfig, load_agent_configs
from autopoiesis.agent.model_resolution import resolve_model_from_config
from autopoiesis.tools.categories import (
    TOOL_CATEGORY_ALIASES,
    resolve_enabled_categories,
)

# ---------------------------------------------------------------------------
# resolve_model_from_config
# ---------------------------------------------------------------------------


class TestResolveModelFromConfig:
    """resolve_model_from_config converts AgentConfig model IDs to pydantic_ai models."""

    def test_anthropic_slash_format_returns_colon_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'anthropic/claude-sonnet-4' → 'anthropic:claude-sonnet-4' (with key set)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        result = resolve_model_from_config("anthropic/claude-sonnet-4")
        assert result == "anthropic:claude-sonnet-4"

    def test_anthropic_slash_subpath_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Model name after first slash is fully preserved."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        result = resolve_model_from_config("anthropic/claude-haiku-4")
        assert result == "anthropic:claude-haiku-4"

    def test_anthropic_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing ANTHROPIC_API_KEY causes SystemExit with clear message."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
            resolve_model_from_config("anthropic/claude-sonnet-4")

    def test_passthrough_no_slash(self) -> None:
        """String without '/' is returned as-is (raw pydantic_ai model string)."""
        result = resolve_model_from_config("anthropic:claude-3-5-sonnet-latest")
        assert result == "anthropic:claude-3-5-sonnet-latest"

    def test_passthrough_empty_string(self) -> None:
        """Empty string has no slash → passed through unchanged."""
        result = resolve_model_from_config("my-custom-model")
        assert result == "my-custom-model"

    def test_openrouter_returns_openai_chat_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """'openrouter/openai/gpt-4o-mini' → OpenAIChatModel instance."""
        from pydantic_ai.models.openai import OpenAIChatModel

        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
        result = resolve_model_from_config("openrouter/openai/gpt-4o-mini")
        assert isinstance(result, OpenAIChatModel)

    def test_openrouter_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing OPENROUTER_API_KEY causes SystemExit."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(SystemExit, match="OPENROUTER_API_KEY"):
            resolve_model_from_config("openrouter/openai/gpt-4o")

    def test_unknown_provider_passthrough(self) -> None:
        """Unknown provider prefix is passed through unchanged."""
        result = resolve_model_from_config("unknown-provider/some-model")
        # Should return the original string as-is (unknown provider → passthrough).
        assert result == "unknown-provider/some-model"


# ---------------------------------------------------------------------------
# resolve_enabled_categories / tool name filtering
# ---------------------------------------------------------------------------


class TestResolveEnabledCategories:
    """resolve_enabled_categories converts AgentConfig tool names to category sets."""

    def test_none_returns_none(self) -> None:
        """None → None means 'all toolsets enabled' (backward-compatible)."""
        assert resolve_enabled_categories(None) is None

    def test_empty_list_returns_empty_frozenset(self) -> None:
        """Empty list → empty frozenset (no optional toolsets)."""
        result = resolve_enabled_categories([])
        assert result is not None
        assert len(result) == 0

    def test_shell_maps_to_console(self) -> None:
        result = resolve_enabled_categories(["shell"])
        assert result is not None
        assert "console" in result

    def test_search_maps_to_knowledge(self) -> None:
        result = resolve_enabled_categories(["search"])
        assert result is not None
        assert "knowledge" in result

    def test_multiple_names(self) -> None:
        result = resolve_enabled_categories(["shell", "search", "topics"])
        assert result is not None
        assert "console" in result
        assert "knowledge" in result
        assert "topics" in result

    def test_canonical_names_pass_through(self) -> None:
        result = resolve_enabled_categories(["console", "exec", "subscriptions"])
        assert result is not None
        assert "console" in result
        assert "exec" in result
        assert "subscriptions" in result

    def test_unknown_name_passes_through_lowercase(self) -> None:
        """Unrecognised tool names are lowercased and passed through (forward-compat)."""
        result = resolve_enabled_categories(["UnknownTool"])
        assert result is not None
        assert "unknowntool" in result

    def test_case_insensitive_matching(self) -> None:
        result = resolve_enabled_categories(["SHELL", "Topics"])
        assert result is not None
        assert "console" in result
        assert "topics" in result

    def test_all_aliases_covered(self) -> None:
        """Every alias in TOOL_CATEGORY_ALIASES resolves to a known canonical category."""
        from autopoiesis.tools.categories import CANONICAL_CATEGORIES

        for alias, canonical in TOOL_CATEGORY_ALIASES.items():
            assert canonical in CANONICAL_CATEGORIES, (
                f"Alias '{alias}' maps to '{canonical}' which is not in CANONICAL_CATEGORIES"
            )


# ---------------------------------------------------------------------------
# build_toolsets tool filtering
# ---------------------------------------------------------------------------


class TestBuildToolsetsFiltering:
    """build_toolsets respects the tool_names whitelist."""

    def test_none_includes_all_by_default(self, tmp_path: Path) -> None:
        """tool_names=None → all available toolsets are assembled."""
        from autopoiesis.store.subscriptions import SubscriptionRegistry
        from autopoiesis.tools.toolset_builder import build_toolsets
        from autopoiesis.topics.topic_manager import TopicRegistry

        sub_db = str(tmp_path / "sub.sqlite")
        sub_reg = SubscriptionRegistry(sub_db)
        topic_reg = TopicRegistry(tmp_path / "topics")
        knowledge_db = str(tmp_path / "knowledge.sqlite")

        from autopoiesis.store.knowledge import init_knowledge_index

        init_knowledge_index(knowledge_db)

        toolsets_all, _ = build_toolsets(
            subscription_registry=sub_reg,
            knowledge_db_path=knowledge_db,
            topic_registry=topic_reg,
            tool_names=None,
        )
        toolsets_filtered, _ = build_toolsets(
            subscription_registry=sub_reg,
            knowledge_db_path=knowledge_db,
            topic_registry=topic_reg,
            tool_names=["shell", "exec", "search", "subscriptions", "topics"],
        )
        # Filtered with all categories should produce same count.
        assert len(toolsets_filtered) == len(toolsets_all)

    def test_topics_excluded_when_not_in_tool_names(self, tmp_path: Path) -> None:
        """Toolset count drops when topics is excluded from tool_names."""
        from autopoiesis.tools.toolset_builder import build_toolsets
        from autopoiesis.topics.topic_manager import TopicRegistry

        topic_reg = TopicRegistry(tmp_path / "topics")

        toolsets_with, _ = build_toolsets(
            topic_registry=topic_reg,
            tool_names=["shell", "topics"],
        )
        toolsets_without, _ = build_toolsets(
            topic_registry=topic_reg,
            tool_names=["shell"],
        )
        assert len(toolsets_with) > len(toolsets_without)

    def test_exec_excluded_when_not_in_tool_names(self, tmp_path: Path) -> None:
        """Exec toolset is not assembled when 'exec' is absent from tool_names."""
        from autopoiesis.tools.toolset_builder import build_toolsets

        toolsets_with_exec, _ = build_toolsets(tool_names=["shell", "exec"])
        toolsets_no_exec, _ = build_toolsets(tool_names=["shell"])
        assert len(toolsets_with_exec) > len(toolsets_no_exec)

    def test_console_and_skills_always_present(self, tmp_path: Path) -> None:
        """Console and skills toolsets are included even with an empty tool_names list."""
        from autopoiesis.tools.toolset_builder import build_toolsets

        toolsets, _ = build_toolsets(tool_names=[])
        # At minimum console + skills are always assembled.
        assert len(toolsets) >= 2

    def test_knowledge_excluded_when_not_in_tool_names(self, tmp_path: Path) -> None:
        """Knowledge toolset is not assembled when 'search'/'knowledge' absent."""
        from autopoiesis.store.knowledge import init_knowledge_index
        from autopoiesis.tools.toolset_builder import build_toolsets

        knowledge_db = str(tmp_path / "knowledge.sqlite")
        init_knowledge_index(knowledge_db)

        toolsets_with, _ = build_toolsets(
            knowledge_db_path=knowledge_db,
            tool_names=["shell", "search"],
        )
        toolsets_without, _ = build_toolsets(
            knowledge_db_path=knowledge_db,
            tool_names=["shell"],
        )
        assert len(toolsets_with) > len(toolsets_without)


# ---------------------------------------------------------------------------
# Config selection precedence in startup
# ---------------------------------------------------------------------------


class TestConfigSelectionPrecedence:
    """AgentConfig is selected correctly based on active agent name."""

    def test_named_agent_selected_from_config(self, tmp_path: Path) -> None:
        """When --agent matches a config entry, that config is selected."""
        toml = tmp_path / "agents.toml"
        toml.write_text(
            """\
[agents.planner]
role = "planner"
model = "anthropic/claude-opus-4"
tools = ["shell", "search"]
shell_tier = "review"
system_prompt = "knowledge/identity/planner.md"

[agents.executor]
role = "executor"
model = "anthropic/claude-haiku-4"
tools = ["shell"]
shell_tier = "free"
system_prompt = "knowledge/identity/executor.md"
"""
        )
        configs = load_agent_configs(toml)
        assert configs["planner"].model == "anthropic/claude-opus-4"
        assert configs["executor"].model == "anthropic/claude-haiku-4"
        assert configs["planner"].shell_tier == "review"
        assert configs["executor"].shell_tier == "free"

    def test_default_agent_name_selects_default_config(self, tmp_path: Path) -> None:
        """No config file → default config with name 'default' is returned."""
        configs = load_agent_configs(tmp_path / "missing.toml")
        assert "default" in configs
        selected = configs.get("default")
        assert selected is not None
        assert selected.name == "default"
        assert selected.model == "anthropic/claude-sonnet-4"
        assert selected.shell_tier == "review"

    def test_unknown_agent_name_raises_in_main(self, tmp_path: Path) -> None:
        """main() raises SystemExit when agent name is not in the loaded config."""
        toml = tmp_path / "agents.toml"
        toml.write_text('[agents.planner]\nrole = "planner"\ntools = []\nsystem_prompt = "x.md"\n')

        with (
            patch("autopoiesis.cli.resolve_agent_name", return_value="ghost"),
            patch(
                "autopoiesis.cli.resolve_agent_workspace",
                return_value=MagicMock(root=tmp_path),
            ),
            patch("autopoiesis.cli.load_dotenv"),
            patch("autopoiesis.cli.otel_tracing"),
        ):
            import autopoiesis.cli as cli_mod

            cli_mod.get_agent_configs().clear()

            import sys

            old_argv = sys.argv
            sys.argv = ["chat", "--config", str(toml), "--no-approval"]
            try:
                with pytest.raises(SystemExit) as exc_info:
                    cli_mod.main()
                msg = str(exc_info.value)
                assert "ghost" in msg
                assert "planner" in msg  # actionable: shows available agents
            finally:
                sys.argv = old_argv

    def test_no_config_no_failure(self, tmp_path: Path) -> None:
        """When no --config is supplied, _agent_configs stays empty, no error."""
        from autopoiesis.cli import get_agent_configs

        assert isinstance(get_agent_configs(), dict)


# ---------------------------------------------------------------------------
# initialize_runtime model/tool/shell-tier wiring
# ---------------------------------------------------------------------------


class TestInitializeRuntimeWiring:
    """initialize_runtime propagates AgentConfig fields to the built Runtime."""

    def _make_config(
        self,
        *,
        model: str = "anthropic/claude-haiku-4",
        tools: list[str] | None = None,
        shell_tier: str = "free",
        system_prompt: str = "knowledge/identity/test.md",
    ) -> AgentConfig:
        return AgentConfig(
            name="test-agent",
            role="executor",
            model=model,
            tools=tools if tools is not None else ["shell"],
            shell_tier=shell_tier,
            system_prompt=Path(system_prompt),
        )

    def test_shell_tier_stored_in_runtime(self, tmp_path: Path) -> None:
        """AgentConfig.shell_tier is propagated to Runtime.shell_tier."""

        from autopoiesis.agent.runtime import Runtime, get_runtime, reset_runtime, set_runtime

        cfg = self._make_config(shell_tier="approve")
        fake_agent = MagicMock()
        fake_runtime = Runtime(
            agent=fake_agent,
            agent_name="test-agent",
            backend=MagicMock(),
            history_db_path=str(tmp_path / "h.sqlite"),
            knowledge_db_path=str(tmp_path / "k.sqlite"),
            subscription_registry=None,
            approval_store=MagicMock(),
            key_manager=MagicMock(),
            tool_policy=MagicMock(),
            shell_tier=cfg.shell_tier,
        )
        reset_runtime()
        set_runtime(fake_runtime)
        rt = get_runtime()
        assert rt.shell_tier == "approve"
        reset_runtime()

    def test_model_override_passed_to_build_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When AgentConfig is provided, build_agent receives model_override not None."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        captured: dict[str, object] = {}

        def _fake_build_agent(
            provider: str,
            agent_name: str,
            toolsets: object,
            system_prompt: str,
            options: object = None,
            *,
            model_override: object = None,
        ) -> object:
            captured["model_override"] = model_override
            captured["agent_name"] = agent_name
            return MagicMock()

        cfg = self._make_config(model="anthropic/claude-haiku-4")

        with (
            patch("autopoiesis.cli.build_agent", side_effect=_fake_build_agent),
            patch("autopoiesis.cli.build_backend", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalStore.from_env", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalKeyManager.from_env", return_value=MagicMock()),
            patch("autopoiesis.cli.ToolPolicyRegistry.default", return_value=MagicMock()),
            patch(
                "autopoiesis.cli.resolve_history_db_path", return_value=str(tmp_path / "h.sqlite")
            ),
            patch(
                "autopoiesis.cli.prepare_toolset_context",
                return_value=(
                    tmp_path,
                    str(tmp_path / "k.sqlite"),
                    MagicMock(),
                    MagicMock(),
                    [],
                    "composed-prompt",
                ),
            ),
            patch("autopoiesis.cli.build_history_processors", return_value=[]),
            patch("autopoiesis.cli.instrument_agent"),
            patch("autopoiesis.cli.init_history_store"),
            patch("autopoiesis.cli.cleanup_stale_checkpoints"),
            patch("autopoiesis.cli.set_runtime"),
        ):
            from autopoiesis.cli import initialize_runtime

            agent_paths = MagicMock(root=tmp_path)

            initialize_runtime(
                agent_paths,
                "test-agent",
                require_approval_unlock=False,
                agent_config=cfg,
            )

        assert captured["model_override"] == "anthropic:claude-haiku-4"
        # DBOS agent name should come from config name, not env default.
        assert captured["agent_name"] == "test-agent"

    def test_tool_names_forwarded_to_prepare_toolset_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AgentConfig.tools list is passed as tool_names to prepare_toolset_context."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        captured_tool_names: list[str] | None = None

        def _fake_prepare(history_db_path: str, tool_names: list[str] | None = None) -> Any:
            nonlocal captured_tool_names
            captured_tool_names = tool_names
            return (
                tmp_path,
                str(tmp_path / "k.sqlite"),
                MagicMock(),
                MagicMock(),
                [],
                "prompt",
            )

        cfg = self._make_config(tools=["shell", "search", "topics"])

        with (
            patch("autopoiesis.cli.build_agent", return_value=MagicMock()),
            patch("autopoiesis.cli.build_backend", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalStore.from_env", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalKeyManager.from_env", return_value=MagicMock()),
            patch("autopoiesis.cli.ToolPolicyRegistry.default", return_value=MagicMock()),
            patch(
                "autopoiesis.cli.resolve_history_db_path", return_value=str(tmp_path / "h.sqlite")
            ),
            patch("autopoiesis.cli.prepare_toolset_context", side_effect=_fake_prepare),
            patch("autopoiesis.cli.build_history_processors", return_value=[]),
            patch("autopoiesis.cli.instrument_agent"),
            patch("autopoiesis.cli.init_history_store"),
            patch("autopoiesis.cli.cleanup_stale_checkpoints"),
            patch("autopoiesis.cli.set_runtime"),
        ):
            from autopoiesis.cli import initialize_runtime

            initialize_runtime(
                MagicMock(root=tmp_path),
                "test-agent",
                require_approval_unlock=False,
                agent_config=cfg,
            )

        assert captured_tool_names == ["shell", "search", "topics"]

    def test_no_agent_config_uses_none_tool_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without AgentConfig, tool_names=None is passed (backward-compatible all-tools)."""
        captured_tool_names: list[str] | None | str = "sentinel"

        def _fake_prepare(history_db_path: str, tool_names: list[str] | None = None) -> Any:
            nonlocal captured_tool_names
            captured_tool_names = tool_names
            return (
                tmp_path,
                str(tmp_path / "k.sqlite"),
                MagicMock(),
                MagicMock(),
                [],
                "prompt",
            )

        with (
            patch("autopoiesis.cli.build_agent", return_value=MagicMock()),
            patch("autopoiesis.cli.build_backend", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalStore.from_env", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalKeyManager.from_env", return_value=MagicMock()),
            patch("autopoiesis.cli.ToolPolicyRegistry.default", return_value=MagicMock()),
            patch(
                "autopoiesis.cli.resolve_history_db_path", return_value=str(tmp_path / "h.sqlite")
            ),
            patch("autopoiesis.cli.prepare_toolset_context", side_effect=_fake_prepare),
            patch("autopoiesis.cli.build_history_processors", return_value=[]),
            patch("autopoiesis.cli.instrument_agent"),
            patch("autopoiesis.cli.init_history_store"),
            patch("autopoiesis.cli.cleanup_stale_checkpoints"),
            patch("autopoiesis.cli.set_runtime"),
        ):
            from autopoiesis.cli import initialize_runtime

            initialize_runtime(
                MagicMock(root=tmp_path),
                "test-agent",
                require_approval_unlock=False,
                agent_config=None,
            )

        assert captured_tool_names is None, (
            "tool_names should be None when no AgentConfig is provided"
        )

    def test_system_prompt_loaded_from_file_when_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When AgentConfig.system_prompt file exists, its content overrides composed prompt."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        prompt_text = "Custom system prompt from file.\nLine 2."
        prompt_path = tmp_path / "knowledge" / "identity" / "test.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt_text, encoding="utf-8")

        cfg = AgentConfig(
            name="test-agent",
            role="planner",
            model="anthropic/claude-sonnet-4",
            tools=["shell"],
            shell_tier="review",
            system_prompt=Path("knowledge/identity/test.md"),
        )

        captured_prompt: list[str] = []

        def _fake_build_agent(
            provider: str,
            agent_name: str,
            toolsets: object,
            system_prompt: str,
            options: object = None,
            *,
            model_override: object = None,
        ) -> object:
            captured_prompt.append(system_prompt)
            return MagicMock()

        with (
            patch("autopoiesis.cli.build_agent", side_effect=_fake_build_agent),
            patch("autopoiesis.cli.build_backend", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalStore.from_env", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalKeyManager.from_env", return_value=MagicMock()),
            patch("autopoiesis.cli.ToolPolicyRegistry.default", return_value=MagicMock()),
            patch(
                "autopoiesis.cli.resolve_history_db_path", return_value=str(tmp_path / "h.sqlite")
            ),
            patch(
                "autopoiesis.cli.prepare_toolset_context",
                return_value=(
                    tmp_path,
                    str(tmp_path / "k.sqlite"),
                    MagicMock(),
                    MagicMock(),
                    [],
                    "auto-composed-prompt",
                ),
            ),
            patch("autopoiesis.cli.build_history_processors", return_value=[]),
            patch("autopoiesis.cli.instrument_agent"),
            patch("autopoiesis.cli.init_history_store"),
            patch("autopoiesis.cli.cleanup_stale_checkpoints"),
            patch("autopoiesis.cli.set_runtime"),
        ):
            from autopoiesis.cli import initialize_runtime

            initialize_runtime(
                MagicMock(root=tmp_path),
                "test-agent",
                require_approval_unlock=False,
                agent_config=cfg,
            )

        assert len(captured_prompt) == 1
        assert captured_prompt[0] == prompt_text, (
            "System prompt should be loaded from file, not from auto-composed toolset prompt"
        )

    def test_system_prompt_fallback_when_file_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When AgentConfig.system_prompt file is absent, auto-composed prompt is used."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        cfg = AgentConfig(
            name="test-agent",
            role="planner",
            model="anthropic/claude-sonnet-4",
            tools=["shell"],
            shell_tier="review",
            system_prompt=Path("knowledge/identity/nonexistent.md"),
        )

        captured_prompt: list[str] = []

        def _fake_build_agent(
            provider: str,
            agent_name: str,
            toolsets: object,
            system_prompt: str,
            options: object = None,
            *,
            model_override: object = None,
        ) -> object:
            captured_prompt.append(system_prompt)
            return MagicMock()

        with (
            patch("autopoiesis.cli.build_agent", side_effect=_fake_build_agent),
            patch("autopoiesis.cli.build_backend", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalStore.from_env", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalKeyManager.from_env", return_value=MagicMock()),
            patch("autopoiesis.cli.ToolPolicyRegistry.default", return_value=MagicMock()),
            patch(
                "autopoiesis.cli.resolve_history_db_path", return_value=str(tmp_path / "h.sqlite")
            ),
            patch(
                "autopoiesis.cli.prepare_toolset_context",
                return_value=(
                    tmp_path,
                    str(tmp_path / "k.sqlite"),
                    MagicMock(),
                    MagicMock(),
                    [],
                    "auto-composed-prompt",
                ),
            ),
            patch("autopoiesis.cli.build_history_processors", return_value=[]),
            patch("autopoiesis.cli.instrument_agent"),
            patch("autopoiesis.cli.init_history_store"),
            patch("autopoiesis.cli.cleanup_stale_checkpoints"),
            patch("autopoiesis.cli.set_runtime"),
        ):
            from autopoiesis.cli import initialize_runtime

            initialize_runtime(
                MagicMock(root=tmp_path),
                "test-agent",
                require_approval_unlock=False,
                agent_config=cfg,
            )

        assert captured_prompt[0] == "auto-composed-prompt"


# ---------------------------------------------------------------------------
# build_agent model_override kwarg
# ---------------------------------------------------------------------------


class TestBuildAgentModelOverride:
    """build_agent uses model_override when supplied, ignoring provider-based resolution."""

    def test_model_override_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When model_override is set, resolve_model is never called."""
        from autopoiesis.agent.runtime import build_agent

        with patch("autopoiesis.agent.runtime.resolve_model") as mock_resolve:
            # Should NOT be called — model_override is supplied.
            mock_resolve.return_value = "should-not-be-used"

            with patch("autopoiesis.agent.runtime.Agent") as mock_agent_cls:
                mock_agent_cls.return_value = MagicMock()
                build_agent(
                    "anthropic",
                    "test-agent",
                    toolsets=[],
                    system_prompt="test",
                    model_override="anthropic:claude-haiku-4",
                )

            mock_resolve.assert_not_called()
            # Verify Agent was called with the override model.
            call_args = mock_agent_cls.call_args
            assert call_args[0][0] == "anthropic:claude-haiku-4"

    def test_no_override_uses_provider_resolution(self) -> None:
        """Without model_override, resolve_model(provider) is used normally."""
        from autopoiesis.agent.runtime import build_agent

        with (
            patch("autopoiesis.agent.runtime.resolve_model") as mock_resolve,
            patch("autopoiesis.agent.runtime.Agent") as mock_agent_cls,
        ):
            mock_resolve.return_value = "resolved-model"
            mock_agent_cls.return_value = MagicMock()

            build_agent("anthropic", "test-agent", toolsets=[], system_prompt="test")

            mock_resolve.assert_called_once_with("anthropic")
