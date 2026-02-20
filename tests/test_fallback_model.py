"""Tests for FallbackModel provider resilience in chat_runtime."""

from __future__ import annotations

import pytest
from _pytest.monkeypatch import MonkeyPatch
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel

from autopoiesis.agent.model_resolution import resolve_model


def test_anthropic_only_no_fallback(monkeypatch: MonkeyPatch) -> None:
    """Single Anthropic key produces a plain model string, not FallbackModel."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    model = resolve_model("anthropic")

    assert isinstance(model, str)
    assert "anthropic" in model


def test_openrouter_only_no_fallback(monkeypatch: MonkeyPatch) -> None:
    """Single OpenRouter key produces an OpenAIChatModel, not FallbackModel."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    model = resolve_model("openrouter")

    assert isinstance(model, OpenAIChatModel)
    assert not isinstance(model, FallbackModel)


@pytest.mark.verifies("CHAT-V5")
def test_both_keys_anthropic_primary(monkeypatch: MonkeyPatch) -> None:
    """Both keys with AI_PROVIDER=anthropic wraps in FallbackModel."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    model = resolve_model("anthropic")

    assert isinstance(model, FallbackModel)
    models = model.models
    assert isinstance(models[0], AnthropicModel)
    assert isinstance(models[1], OpenAIChatModel)


def test_both_keys_openrouter_primary(monkeypatch: MonkeyPatch) -> None:
    """Both keys with AI_PROVIDER=openrouter puts OpenRouter first."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    model = resolve_model("openrouter")

    assert isinstance(model, FallbackModel)
    models = model.models
    assert isinstance(models[0], OpenAIChatModel)
    assert isinstance(models[1], AnthropicModel)
