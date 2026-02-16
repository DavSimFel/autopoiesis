"""Agent runtime, worker, CLI, and context management.

Public API: Runtime, AgentOptions, build_agent, cli_chat_loop, enqueue_and_wait
Internal: cli, context, runtime, truncation, worker
"""

from agent.cli import cli_chat_loop
from agent.context import compact_history
from agent.runtime import (
    AgentOptions,
    Runtime,
    build_agent,
    get_runtime,
    instrument_agent,
    set_runtime,
)
from agent.truncation import truncate_tool_results
from agent.worker import checkpoint_history_processor, enqueue, enqueue_and_wait

__all__ = [
    "AgentOptions",
    "Runtime",
    "build_agent",
    "checkpoint_history_processor",
    "cli_chat_loop",
    "compact_history",
    "enqueue",
    "enqueue_and_wait",
    "get_runtime",
    "instrument_agent",
    "set_runtime",
    "truncate_tool_results",
]
