"""Agent runtime, worker, CLI, and context management.

Public API: AgentOptions, AgentRegistry, Runtime, build_agent,
    checkpoint_history_processor, cli_chat_loop, compact_history,
    enqueue, enqueue_and_wait, get_runtime, instrument_agent,
    register_runtime, set_runtime, truncate_tool_results
Internal: cli, context, runtime, truncation, worker
"""

from autopoiesis.agent.cli import cli_chat_loop
from autopoiesis.agent.context import compact_history
from autopoiesis.agent.runtime import (
    AgentOptions,
    AgentRegistry,
    Runtime,
    build_agent,
    get_runtime,
    instrument_agent,
    register_runtime,
    set_runtime,
)
from autopoiesis.agent.truncation import truncate_tool_results
from autopoiesis.agent.worker import checkpoint_history_processor, enqueue, enqueue_and_wait

__all__ = [
    "AgentOptions",
    "AgentRegistry",
    "Runtime",
    "build_agent",
    "checkpoint_history_processor",
    "cli_chat_loop",
    "compact_history",
    "enqueue",
    "enqueue_and_wait",
    "get_runtime",
    "instrument_agent",
    "register_runtime",
    "set_runtime",
    "truncate_tool_results",
]
