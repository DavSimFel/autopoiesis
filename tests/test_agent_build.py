"""Basic agent construction and run test using PydanticAI TestModel."""

from __future__ import annotations

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from autopoiesis.models import AgentDeps


@pytest.mark.asyncio()
async def test_agent_runs_with_test_model(mock_deps: AgentDeps) -> None:
    """Verify the agent can be constructed and produce a response via TestModel."""
    agent: Agent[AgentDeps, str] = Agent(
        TestModel(),
        deps_type=AgentDeps,
        instructions=["You are a test assistant."],
    )
    result = await agent.run("Hello", deps=mock_deps)
    assert isinstance(result.output, str)
    assert len(result.output) > 0
