"""Observable toolset wrapper for logging tool call metrics.

Wraps any ``AbstractToolset`` to intercept ``call_tool`` and log timing,
success/failure, and tool metadata via the standard ``logging`` module.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.toolsets.wrapper import WrapperToolset

from models import AgentDeps

logger = logging.getLogger(__name__)


class ObservableToolset(WrapperToolset[AgentDeps]):
    """Intercepts every tool call to log name, duration, and outcome."""

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDeps],
        tool: Any,
    ) -> Any:
        """Delegate to the wrapped toolset while logging call metrics."""
        start = time.monotonic()
        try:
            result = await super().call_tool(name, tool_args, ctx, tool)
        except Exception:
            elapsed = time.monotonic() - start
            logger.error("tool_call name=%s duration=%.3fs status=error", name, elapsed)
            raise
        elapsed = time.monotonic() - start
        logger.info("tool_call name=%s duration=%.3fs status=ok", name, elapsed)
        return result


def wrap_toolsets(
    toolsets: list[AbstractToolset[AgentDeps]],
) -> list[AbstractToolset[AgentDeps]]:
    """Wrap each toolset in an ``ObservableToolset`` for observability."""
    return [ObservableToolset(ts) for ts in toolsets]
