"""Tests for OpenTelemetry agent instrumentation toggle."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

from pydantic_ai import Agent

from chat_runtime import instrument_agent
from models import AgentDeps


def _mock_agent() -> Agent[AgentDeps, str]:
    return cast(Agent[AgentDeps, str], MagicMock())


def test_instrument_called_when_endpoint_set() -> None:
    """instrument_all() is invoked when OTEL_EXPORTER_OTLP_ENDPOINT is present."""
    agent = _mock_agent()
    with (
        patch.dict("os.environ", {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"}),
        patch("chat_runtime.Agent") as mock_cls,
    ):
        result = instrument_agent(agent)

    assert result is True
    mock_cls.instrument_all.assert_called_once()


def test_instrument_skipped_when_endpoint_absent() -> None:
    """instrument_all() is NOT invoked when the env var is missing."""
    agent = _mock_agent()
    import os

    with patch.dict("os.environ", {}, clear=False):
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        with patch("chat_runtime.Agent") as mock_cls:
            result = instrument_agent(agent)

    assert result is False
    mock_cls.instrument_all.assert_not_called()
