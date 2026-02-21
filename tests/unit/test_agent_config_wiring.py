"""Unit tests for AgentConfig → runtime construction wiring (Issue #201).

Acceptance criteria:
1. Runtime startup selects AgentConfig for active agent and uses it to build
   model, tools, and shell tier behaviour.
2. Missing/unknown agent config fails fast with an actionable error.
3. Default behaviour remains backward compatible when no config file is present.
4. Unit tests cover config selection precedence and model/tool assignment from config.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import AbstractToolset

from autopoiesis.agent.config import AgentConfig
from autopoiesis.models import AgentDeps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    name: str = "default",
    model: str = "anthropic/claude-sonnet-4",
    tools: list[str] | None = None,
    shell_tier: str = "review",
) -> AgentConfig:
    return AgentConfig(
        name=name,
        role="planner",
        model=model,
        tools=tools or ["shell", "search", "topics"],
        shell_tier=shell_tier,
        system_prompt=Path(f"knowledge/identity/{name}.md"),
    )


def _identity_toolsets(toolsets: list[Any]) -> list[Any]:
    return toolsets


# ---------------------------------------------------------------------------
# 1. Model resolution from AgentConfig
# ---------------------------------------------------------------------------


class TestResolveModelFromConfig:
    """resolve_model_from_config() derives provider from the model name prefix."""

    def test_anthropic_prefix_returns_string(self) -> None:
        from autopoiesis.agent.model_resolution import resolve_model_from_config

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = resolve_model_from_config("anthropic/claude-sonnet-4")
        # pydantic-ai accepts "anthropic:model" string tokens
        assert isinstance(result, str)
        assert result.startswith("anthropic:")
        assert "claude-sonnet-4" in result

    def test_openai_prefix_returns_model_instance(self) -> None:
        from autopoiesis.agent.model_resolution import resolve_model_from_config

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            result = resolve_model_from_config("openai/gpt-4o-mini")
        # Should be an OpenAIChatModel instance
        from pydantic_ai.models.openai import OpenAIChatModel

        assert isinstance(result, OpenAIChatModel)

    def test_anthropic_prefix_requires_api_key(self) -> None:
        from autopoiesis.agent.model_resolution import resolve_model_from_config

        env = {"ANTHROPIC_API_KEY": ""}
        with (
            patch.dict("os.environ", env, clear=False),
            pytest.raises(SystemExit),
            patch("autopoiesis.agent.model_resolution.os.getenv", return_value=""),
        ):
            resolve_model_from_config("anthropic/claude-3-5-sonnet-latest")

    def test_openrouter_requires_api_key(self) -> None:
        from autopoiesis.agent.model_resolution import resolve_model_from_config

        with (
            patch("autopoiesis.agent.model_resolution.os.getenv", return_value=""),
            pytest.raises(SystemExit),
        ):
            resolve_model_from_config("openai/gpt-4o")

    def test_anthropic_slash_converts_to_colon(self) -> None:
        from autopoiesis.agent.model_resolution import resolve_model_from_config

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = resolve_model_from_config("anthropic/claude-3-5-sonnet-latest")
        assert result == "anthropic:claude-3-5-sonnet-latest"

    def test_no_prefix_defaults_to_openrouter(self) -> None:
        from autopoiesis.agent.model_resolution import infer_provider_from_model_name

        assert infer_provider_from_model_name("gpt-4o") == "openrouter"

    def test_anthropic_prefix_inferred(self) -> None:
        from autopoiesis.agent.model_resolution import infer_provider_from_model_name

        assert infer_provider_from_model_name("anthropic/claude-3-opus") == "anthropic"

    def test_openai_prefix_inferred_as_openrouter(self) -> None:
        from autopoiesis.agent.model_resolution import infer_provider_from_model_name

        assert infer_provider_from_model_name("openai/gpt-4o") == "openrouter"


# ---------------------------------------------------------------------------
# 2. build_agent_from_config uses config fields
# ---------------------------------------------------------------------------


class TestBuildAgentFromConfig:
    """build_agent_from_config() derives model and name directly from AgentConfig."""

    def test_constructor_uses_config_name_model_and_prepare_tools(self) -> None:
        from autopoiesis.agent.runtime import build_agent_from_config

        cfg = _make_config(name="planner", model="anthropic/claude-sonnet-4")
        mock_toolsets = cast(list[AbstractToolset[AgentDeps]], [MagicMock()])
        mock_agent = MagicMock()
        resolved_model = "anthropic:claude-sonnet-4"
        with patch(
            "autopoiesis.agent.runtime.resolve_model_from_config",
            return_value=resolved_model,
        ), patch("autopoiesis.agent.runtime.Agent", return_value=mock_agent) as mock_ctor:
            result = build_agent_from_config(cfg, mock_toolsets, "system prompt")
        assert result is mock_agent
        call = mock_ctor.call_args
        assert call is not None
        assert call.args[0] == resolved_model
        assert call.kwargs["name"] == "planner"
        assert call.kwargs["toolsets"] == mock_toolsets
        assert call.kwargs["prepare_tools"] is None
        assert call.kwargs["system_prompt"] == "system prompt"

    def test_model_derived_from_config_not_env(self) -> None:
        """Config model takes priority over AI_PROVIDER env var."""
        from autopoiesis.agent.runtime import build_agent_from_config

        cfg = _make_config(name="coder", model="openai/gpt-4o")
        with (
            patch(
                "autopoiesis.agent.runtime.resolve_model_from_config",
                return_value=MagicMock(),
            ) as mock_resolve,
            patch("autopoiesis.agent.runtime.Agent", return_value=MagicMock()),
            patch.dict("os.environ", {"AI_PROVIDER": "anthropic"}),
        ):
            build_agent_from_config(cfg, [], "prompt")
            mock_resolve.assert_called_once_with("openai/gpt-4o")

    def test_openrouter_config_sets_strict_prepare_tools(self) -> None:
        """OpenRouter path should wire strict_tool_definitions callback."""
        from autopoiesis.agent.runtime import build_agent_from_config

        cfg = _make_config(model="openai/gpt-4o-mini")
        mock_openrouter_model = MagicMock()
        with patch(
            "autopoiesis.agent.runtime.resolve_model_from_config",
            return_value=mock_openrouter_model,
        ), patch("autopoiesis.agent.runtime.Agent", return_value=MagicMock()) as mock_ctor:
            build_agent_from_config(cfg, [], "prompt")
        call = mock_ctor.call_args
        assert call is not None
        assert call.kwargs["prepare_tools"].__name__ == "strict_tool_definitions"

    def test_real_construction_smoke_anthropic(self) -> None:
        from autopoiesis.agent.runtime import build_agent_from_config

        cfg = _make_config(name="anthro-smoke", model="anthropic/claude-sonnet-4")
        with patch.dict(
            "os.environ",
            {
                "ANTHROPIC_API_KEY": "test-key",
                "OPENROUTER_API_KEY": "",
                "OPENAI_API_KEY": "",
                "AI_PROVIDER": "anthropic",
                "ANTHROPIC_MODEL": "anthropic:claude-sonnet-4",
            },
            clear=False,
        ):
            agent = build_agent_from_config(cfg, [], "prompt")
        assert agent.name == "anthro-smoke"

    def test_real_construction_smoke_openrouter(self) -> None:
        from autopoiesis.agent.runtime import build_agent_from_config

        cfg = _make_config(name="openrouter-smoke", model="openai/gpt-4o-mini")
        with patch.dict(
            "os.environ",
            {
                "ANTHROPIC_API_KEY": "",
                "OPENROUTER_API_KEY": "test-key",
                "OPENAI_API_KEY": "",
                "AI_PROVIDER": "openrouter",
                "ANTHROPIC_MODEL": "",
            },
            clear=False,
        ):
            agent = build_agent_from_config(cfg, [], "prompt")
        assert agent.name == "openrouter-smoke"


# ---------------------------------------------------------------------------
# 3. Toolset filtering from config.tools
# ---------------------------------------------------------------------------


class TestBuildToolsetsForAgent:
    """build_toolsets() filters toolset assembly by tool name list."""

    def test_none_tool_names_enables_optional_toolsets(self) -> None:
        """None means optional categories are enabled (backward-compatible)."""
        from autopoiesis.tools.toolset_builder import build_toolsets

        mock_console = MagicMock(name="console")
        mock_skills = MagicMock(name="skills")
        mock_exec = MagicMock(name="exec")
        with (
            patch("autopoiesis.tools.toolset_builder.validate_console_deps_contract"),
            patch(
                "autopoiesis.tools.toolset_builder.create_console_toolset",
                return_value=mock_console,
            ),
            patch(
                "autopoiesis.tools.toolset_builder.create_skills_toolset",
                return_value=(mock_skills, "skills"),
            ),
            patch(
                "autopoiesis.tools.toolset_builder._build_exec_toolset",
                return_value=mock_exec,
            ),
            patch(
                "autopoiesis.tools.toolset_builder.wrap_toolsets",
                side_effect=_identity_toolsets,
            ),
            patch("autopoiesis.tools.toolset_builder.compose_system_prompt", return_value="prompt"),
        ):
            toolsets, _ = build_toolsets(tool_names=None)
            assert mock_console in toolsets
            assert mock_skills in toolsets
            assert mock_exec in toolsets

    def test_empty_tools_includes_only_core_toolsets(self) -> None:
        """Empty list disables optional categories and keeps core toolsets."""
        from autopoiesis.tools.toolset_builder import build_toolsets

        mock_console = MagicMock(name="console")
        mock_exec = MagicMock(name="exec")
        mock_skills = MagicMock(name="skills")

        with (
            patch("autopoiesis.tools.toolset_builder.validate_console_deps_contract"),
            patch(
                "autopoiesis.tools.toolset_builder.create_console_toolset",
                return_value=mock_console,
            ),
            patch(
                "autopoiesis.tools.toolset_builder.create_skills_toolset",
                return_value=(mock_skills, "skills-instr"),
            ),
            patch("autopoiesis.tools.toolset_builder._build_exec_toolset", return_value=mock_exec),
            patch(
                "autopoiesis.tools.toolset_builder.wrap_toolsets",
                side_effect=_identity_toolsets,
            ),
            patch("autopoiesis.tools.toolset_builder.compose_system_prompt", return_value="prompt"),
            patch("autopoiesis.tools.toolset_builder.create_knowledge_toolset") as mock_kb,
            patch("autopoiesis.tools.toolset_builder.create_topic_toolset") as mock_topic,
            patch("autopoiesis.tools.toolset_builder.create_subscription_toolset") as mock_sub,
        ):
            toolsets, _ = build_toolsets(tool_names=[])
            mock_kb.assert_not_called()
            mock_topic.assert_not_called()
            mock_sub.assert_not_called()
            assert mock_console in toolsets
            assert mock_exec not in toolsets
            assert mock_skills in toolsets

    def test_shell_only_includes_core_toolsets(self) -> None:
        """When tools=['shell'], alias maps to console-only optional behavior."""
        from autopoiesis.tools.toolset_builder import build_toolsets

        mock_console = MagicMock(name="console")
        mock_exec = MagicMock(name="exec")
        mock_skills = MagicMock(name="skills")

        with (
            patch("autopoiesis.tools.toolset_builder.validate_console_deps_contract"),
            patch(
                "autopoiesis.tools.toolset_builder.create_console_toolset",
                return_value=mock_console,
            ),
            patch(
                "autopoiesis.tools.toolset_builder.create_skills_toolset",
                return_value=(mock_skills, "skills-instr"),
            ),
            patch("autopoiesis.tools.toolset_builder._build_exec_toolset", return_value=mock_exec),
            patch(
                "autopoiesis.tools.toolset_builder.wrap_toolsets",
                side_effect=_identity_toolsets,
            ),
            patch("autopoiesis.tools.toolset_builder.compose_system_prompt", return_value="prompt"),
            patch("autopoiesis.tools.toolset_builder.create_knowledge_toolset") as mock_kb,
            patch("autopoiesis.tools.toolset_builder.create_topic_toolset") as mock_topic,
            patch("autopoiesis.tools.toolset_builder.create_subscription_toolset") as mock_sub,
        ):
            toolsets, _ = build_toolsets(tool_names=["shell"])
            mock_kb.assert_not_called()
            mock_topic.assert_not_called()
            mock_sub.assert_not_called()
            assert mock_console in toolsets
            assert mock_exec not in toolsets
            assert mock_skills in toolsets

    def test_search_includes_knowledge_toolset(self) -> None:
        """When 'search' in tools and knowledge_db_path given, knowledge toolset included."""
        from autopoiesis.tools.toolset_builder import build_toolsets

        mock_kb_toolset = MagicMock(name="knowledge")
        mock_skills = MagicMock(name="skills")

        with (
            patch("autopoiesis.tools.toolset_builder.validate_console_deps_contract"),
            patch(
                "autopoiesis.tools.toolset_builder.create_console_toolset",
                return_value=MagicMock(),
            ),
            patch(
                "autopoiesis.tools.toolset_builder.create_skills_toolset",
                return_value=(mock_skills, "skills-instr"),
            ),
            patch(
                "autopoiesis.tools.toolset_builder._build_exec_toolset",
                return_value=MagicMock(),
            ),
            patch(
                "autopoiesis.tools.toolset_builder.create_knowledge_toolset",
                return_value=(mock_kb_toolset, "kb-instr"),
            ) as mock_create_kb,
            patch(
                "autopoiesis.tools.toolset_builder.wrap_toolsets",
                side_effect=_identity_toolsets,
            ),
            patch("autopoiesis.tools.toolset_builder.compose_system_prompt", return_value="prompt"),
        ):
            toolsets, _ = build_toolsets(
                tool_names=["shell", "search"],
                knowledge_db_path="/tmp/knowledge.sqlite",
            )
            mock_create_kb.assert_called_once_with("/tmp/knowledge.sqlite")
            assert mock_kb_toolset in toolsets

    def test_search_excluded_when_not_in_tools(self) -> None:
        """Knowledge toolset NOT included when 'search' absent from tools list."""
        from autopoiesis.tools.toolset_builder import build_toolsets

        with (
            patch("autopoiesis.tools.toolset_builder.validate_console_deps_contract"),
            patch(
                "autopoiesis.tools.toolset_builder.create_console_toolset",
                return_value=MagicMock(),
            ),
            patch(
                "autopoiesis.tools.toolset_builder.create_skills_toolset",
                return_value=(MagicMock(), ""),
            ),
            patch(
                "autopoiesis.tools.toolset_builder._build_exec_toolset",
                return_value=MagicMock(),
            ),
            patch("autopoiesis.tools.toolset_builder.create_knowledge_toolset") as mock_kb,
            patch(
                "autopoiesis.tools.toolset_builder.wrap_toolsets",
                side_effect=_identity_toolsets,
            ),
            patch("autopoiesis.tools.toolset_builder.compose_system_prompt", return_value=""),
        ):
            build_toolsets(tool_names=["shell"])
            mock_kb.assert_not_called()


# ---------------------------------------------------------------------------
# 4. CLI config selection precedence
# ---------------------------------------------------------------------------


class TestConfigSelectionPrecedence:
    """Config selection in main(): cli flag > env var > no config."""

    def test_no_config_path_skips_loading(self, tmp_path: Path) -> None:
        """When no --config and no env var, configs are not loaded."""
        from autopoiesis import cli as cli_mod

        # Clear module-level registry
        cli_mod.get_agent_configs().clear()

        with (
            patch("autopoiesis.cli.parse_cli_args") as mock_args,
            patch("autopoiesis.cli.resolve_agent_name", return_value="default"),
            patch("autopoiesis.cli.resolve_agent_workspace"),
            patch("autopoiesis.cli.load_dotenv"),
            patch("autopoiesis.cli.otel_tracing.configure"),
            patch("autopoiesis.cli.initialize_runtime", return_value="sqlite:///test.sqlite"),
            patch("autopoiesis.cli.DBOS"),
            patch.dict("os.environ", {}, clear=True),
        ):
            mock_args.return_value = MagicMock(
                command=None,
                agent=None,
                no_approval=True,
                config=None,
            )
            with contextlib.suppress(Exception):
                cli_mod.main()
        assert cli_mod.get_agent_configs() == {}

    def test_unknown_agent_exits_fast(self, tmp_path: Path) -> None:
        """When config is loaded but agent not found, SystemExit with actionable error."""
        from autopoiesis import cli as cli_mod

        config_file = tmp_path / "agents.toml"
        config_file.write_text('[agents.planner]\nrole = "planner"\n')
        cli_mod.get_agent_configs().clear()

        with (
            patch("autopoiesis.cli.parse_cli_args") as mock_args,
            patch("autopoiesis.cli.resolve_agent_name", return_value="missing-agent"),
            patch("autopoiesis.cli.resolve_agent_workspace"),
            patch("autopoiesis.cli.load_dotenv"),
            patch("autopoiesis.cli.otel_tracing.configure"),
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(SystemExit) as exc_info,
        ):
            mock_args.return_value = MagicMock(
                command=None,
                agent="missing-agent",
                no_approval=True,
                config=str(config_file),
            )
            cli_mod.main()

        assert "missing-agent" in str(exc_info.value)
        assert "planner" in str(exc_info.value)

    def test_valid_agent_in_config_selects_config(self, tmp_path: Path) -> None:
        """When agent name is found in loaded configs, AgentConfig is passed to runtime."""
        from autopoiesis import cli as cli_mod

        config_file = tmp_path / "agents.toml"
        config_file.write_text('[agents.coder]\nrole = "executor"\nmodel = "openai/gpt-4o"\n')
        cli_mod.get_agent_configs().clear()

        captured_config: list[AgentConfig | None] = []

        def fake_initialize_runtime(
            *args: object,
            agent_config: AgentConfig | None = None,
            **kwargs: object,
        ) -> str:
            captured_config.append(agent_config)
            return "sqlite:///test.sqlite"

        with (
            patch("autopoiesis.cli.parse_cli_args") as mock_args,
            patch("autopoiesis.cli.resolve_agent_name", return_value="coder"),
            patch("autopoiesis.cli.resolve_agent_workspace"),
            patch("autopoiesis.cli.load_dotenv"),
            patch("autopoiesis.cli.otel_tracing.configure"),
            patch("autopoiesis.cli.initialize_runtime", side_effect=fake_initialize_runtime),
            patch("autopoiesis.cli.DBOS"),
            patch.dict("os.environ", {}, clear=True),
        ):
            mock_args.return_value = MagicMock(
                command=None,
                agent="coder",
                no_approval=True,
                config=str(config_file),
            )
            with contextlib.suppress(Exception):
                cli_mod.main()

        assert len(captured_config) == 1
        cfg = captured_config[0]
        assert cfg is not None
        assert cfg.name == "coder"
        assert cfg.model == "openai/gpt-4o"

    def test_no_config_passes_none_to_runtime(self, tmp_path: Path) -> None:
        """When no config file, agent_config=None is passed to initialize_runtime."""
        from autopoiesis import cli as cli_mod

        cli_mod.get_agent_configs().clear()
        captured_config: list[AgentConfig | None] = []

        def fake_initialize_runtime(
            *args: object,
            agent_config: AgentConfig | None = None,
            **kwargs: object,
        ) -> str:
            captured_config.append(agent_config)
            return "sqlite:///test.sqlite"

        with (
            patch("autopoiesis.cli.parse_cli_args") as mock_args,
            patch("autopoiesis.cli.resolve_agent_name", return_value="default"),
            patch("autopoiesis.cli.resolve_agent_workspace"),
            patch("autopoiesis.cli.load_dotenv"),
            patch("autopoiesis.cli.otel_tracing.configure"),
            patch("autopoiesis.cli.initialize_runtime", side_effect=fake_initialize_runtime),
            patch("autopoiesis.cli.DBOS"),
            patch.dict("os.environ", {}, clear=True),
        ):
            mock_args.return_value = MagicMock(
                command=None,
                agent=None,
                no_approval=True,
                config=None,
            )
            with contextlib.suppress(Exception):
                cli_mod.main()

        assert len(captured_config) == 1
        assert captured_config[0] is None


# ---------------------------------------------------------------------------
# 5. prepare_toolset_context passes tool_names from agent config
# ---------------------------------------------------------------------------


class TestInitializeRuntimePassesToolNames:
    """initialize_runtime passes config.tools as tool_names to toolset context."""

    def test_config_tools_forwarded_to_prepare_toolset_context(self, tmp_path: Path) -> None:
        from autopoiesis.agent.workspace import resolve_agent_workspace
        from autopoiesis.cli import initialize_runtime

        cfg = _make_config(
            name="filtered",
            model="anthropic/claude-sonnet-4",
            tools=["shell", "search"],
        )

        captured_tool_names: list[list[str] | None] = []

        def fake_prepare(
            *args: object,
            tool_names: list[str] | None = None,
            **kwargs: object,
        ) -> tuple[Path, str, MagicMock, MagicMock, list[Any], str]:
            captured_tool_names.append(tool_names)
            mock_registry = MagicMock()
            mock_registry.get_active.return_value = []
            return (
                tmp_path / "workspace",
                str(tmp_path / "knowledge.sqlite"),
                mock_registry,
                MagicMock(),
                [],
                "system prompt",
            )

        agent_paths = resolve_agent_workspace("filtered-test")

        with (
            patch(
                "autopoiesis.cli._resolve_startup_config",
                return_value=("anthropic", "sqlite:///test.sqlite"),
            ),
            patch("autopoiesis.cli.build_backend", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalStore") as mock_as,
            patch("autopoiesis.cli.ApprovalKeyManager") as mock_km,
            patch("autopoiesis.cli.ToolPolicyRegistry"),
            patch(
                "autopoiesis.cli.resolve_history_db_path",
                return_value=str(tmp_path / "history.sqlite"),
            ),
            patch("autopoiesis.cli.prepare_toolset_context", side_effect=fake_prepare),
            patch("autopoiesis.cli.build_history_processors", return_value=[]),
            patch(
                "autopoiesis.cli.resolve_model_from_config",
                return_value="anthropic:claude-sonnet-4",
            ),
            patch("autopoiesis.cli.build_agent", return_value=MagicMock()),
            patch("autopoiesis.cli.instrument_agent"),
            patch("autopoiesis.cli.init_history_store"),
            patch("autopoiesis.cli.cleanup_stale_checkpoints"),
            patch("autopoiesis.cli.register_runtime"),
            patch("autopoiesis.cli.set_runtime"),
        ):
            mock_as.from_env.return_value = MagicMock()
            mock_km.from_env.return_value = MagicMock()
            initialize_runtime(
                agent_paths,
                "filtered-test",
                require_approval_unlock=False,
                agent_config=cfg,
            )

        assert captured_tool_names == [["shell", "search"]]

    def test_no_config_passes_none_tool_names(self, tmp_path: Path) -> None:
        from autopoiesis.agent.workspace import resolve_agent_workspace
        from autopoiesis.cli import initialize_runtime

        captured_tool_names: list[list[str] | None] = []

        def fake_prepare(
            *args: object,
            tool_names: list[str] | None = None,
            **kwargs: object,
        ) -> tuple[Path, str, MagicMock, MagicMock, list[Any], str]:
            captured_tool_names.append(tool_names)
            mock_registry = MagicMock()
            mock_registry.get_active.return_value = []
            return (
                tmp_path / "workspace",
                str(tmp_path / "knowledge.sqlite"),
                mock_registry,
                MagicMock(),
                [],
                "system prompt",
            )

        agent_paths = resolve_agent_workspace("default-test")

        with (
            patch(
                "autopoiesis.cli._resolve_startup_config",
                return_value=("anthropic", "sqlite:///test.sqlite"),
            ),
            patch("autopoiesis.cli.build_backend", return_value=MagicMock()),
            patch("autopoiesis.cli.ApprovalStore") as mock_as,
            patch("autopoiesis.cli.ApprovalKeyManager") as mock_km,
            patch("autopoiesis.cli.ToolPolicyRegistry"),
            patch(
                "autopoiesis.cli.resolve_history_db_path",
                return_value=str(tmp_path / "history.sqlite"),
            ),
            patch("autopoiesis.cli.prepare_toolset_context", side_effect=fake_prepare),
            patch("autopoiesis.cli.build_history_processors", return_value=[]),
            patch("autopoiesis.cli.build_agent", return_value=MagicMock()),
            patch("autopoiesis.cli.instrument_agent"),
            patch("autopoiesis.cli.init_history_store"),
            patch("autopoiesis.cli.cleanup_stale_checkpoints"),
            patch("autopoiesis.cli.register_runtime"),
            patch("autopoiesis.cli.set_runtime"),
        ):
            mock_as.from_env.return_value = MagicMock()
            mock_km.from_env.return_value = MagicMock()
            initialize_runtime(
                agent_paths,
                "default-test",
                require_approval_unlock=False,
                agent_config=None,
            )

        assert captured_tool_names == [None]
