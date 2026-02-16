"""Tests for model_settings env loading and end_strategy wiring."""

from __future__ import annotations

import os
from unittest.mock import patch

from pydantic_ai.settings import ModelSettings

from chat_runtime import AgentOptions, build_agent
from model_resolution import build_model_settings

_TEMP_HALF = 0.5
_TEMP_LOW = 0.3
_TEMP_POINT_TWO = 0.2
_TOP_P_HIGH = 0.9
_TOP_P_MID = 0.8
_MAX_TOKENS_4K = 4096
_MAX_TOKENS_2K = 2048
_MAX_TOKENS_1K = 1024


class TestBuildModelSettings:
    """Verify build_model_settings reads env vars correctly."""

    def test_returns_none_when_no_env_vars(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert build_model_settings() is None

    def test_reads_temperature(self) -> None:
        with patch.dict(os.environ, {"AI_TEMPERATURE": "0.5"}, clear=True):
            settings = build_model_settings()
            assert settings is not None
            assert settings.get("temperature") == _TEMP_HALF

    def test_reads_max_tokens(self) -> None:
        with patch.dict(os.environ, {"AI_MAX_TOKENS": "4096"}, clear=True):
            settings = build_model_settings()
            assert settings is not None
            assert settings.get("max_tokens") == _MAX_TOKENS_4K

    def test_reads_top_p(self) -> None:
        with patch.dict(os.environ, {"AI_TOP_P": "0.9"}, clear=True):
            settings = build_model_settings()
            assert settings is not None
            assert settings.get("top_p") == _TOP_P_HIGH

    def test_reads_all_vars(self) -> None:
        env = {
            "AI_TEMPERATURE": "0.3",
            "AI_MAX_TOKENS": "2048",
            "AI_TOP_P": "0.8",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = build_model_settings()
            assert settings is not None
            assert settings.get("temperature") == _TEMP_LOW
            assert settings.get("max_tokens") == _MAX_TOKENS_2K
            assert settings.get("top_p") == _TOP_P_MID


class TestBuildAgentEndStrategy:
    """Verify build_agent sets end_strategy and model_settings."""

    def test_anthropic_agent_has_exhaustive_end_strategy(self) -> None:
        env = {
            "ANTHROPIC_API_KEY": "test-key",
            "ANTHROPIC_MODEL": "anthropic:claude-3-5-sonnet-latest",
        }
        with patch.dict(os.environ, env):
            agent = build_agent(
                provider="anthropic",
                agent_name="test",
                toolsets=[],
                system_prompt="test",
                options=AgentOptions(instructions=[]),
            )
            assert agent.end_strategy == "exhaustive"

    def test_anthropic_agent_applies_model_settings(self) -> None:
        env = {"ANTHROPIC_API_KEY": "test-key"}
        with patch.dict(os.environ, env):
            settings: ModelSettings = {
                "temperature": _TEMP_POINT_TWO,
                "max_tokens": _MAX_TOKENS_1K,
            }
            agent = build_agent(
                provider="anthropic",
                agent_name="test",
                toolsets=[],
                system_prompt="test",
                options=AgentOptions(instructions=[], model_settings=settings),
            )
            ms = agent.model_settings
            assert ms is not None
            assert ms.get("temperature") == _TEMP_POINT_TWO
            assert ms.get("max_tokens") == _MAX_TOKENS_1K
