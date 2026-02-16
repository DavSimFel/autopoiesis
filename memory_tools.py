"""PydanticAI tool definitions for persistent chat memory.

Exposes memory_search, memory_get, and memory_save as agent tools backed
by the SQLite FTS5 memory store and workspace memory files.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from memory_store import combined_search, get_memory_file_snippet, save_memory
from models import AgentDeps

_MEMORY_INSTRUCTIONS = (
    "You have persistent memory tools for retaining knowledge across sessions.\n"
    "- Before answering questions about prior work, decisions, or preferences, "
    "search memory first.\n"
    "- Write key decisions and reasoning to MEMORY.md.\n"
    "- Keep MEMORY.md under 200 lines — distill, don't append.\n"
    "Use memory_search to find past context, memory_get to read memory file "
    "snippets, and memory_save to persist important information."
)


def create_memory_toolset(
    db_path: str,
    workspace_root: Path,
) -> tuple[FunctionToolset[AgentDeps], str]:
    """Create memory tools and return the toolset with instructions."""
    toolset: FunctionToolset[AgentDeps] = FunctionToolset(
        docstring_format="google",
        require_parameter_descriptions=True,
    )

    @toolset.tool
    async def memory_search(
        ctx: RunContext[AgentDeps],
        query: str,
        max_results: int = 5,
    ) -> str:
        """Search persistent memory (database + files) for past context.

        Args:
            query: Search query string to match against stored memories.
            max_results: Maximum number of results to return.
        """
        return combined_search(db_path, workspace_root, query, max_results)

    @toolset.tool
    async def memory_get(
        ctx: RunContext[AgentDeps],
        path: str,
        from_line: int | None = None,
        lines: int | None = None,
    ) -> str:
        """Read a snippet from a workspace memory file.

        Args:
            path: Relative path to the memory file within the workspace.
            from_line: Line number to start reading from (1-indexed).
            lines: Number of lines to read from the starting position.
        """
        return get_memory_file_snippet(workspace_root, path, from_line, lines)

    @toolset.tool
    async def memory_save(
        ctx: RunContext[AgentDeps],
        summary: str,
        topics: list[str],
    ) -> str:
        """Save a memory entry for future retrieval.

        Args:
            summary: Text content of the memory to persist.
            topics: List of topic tags for categorizing the memory.
        """
        entry_id = save_memory(db_path, summary, topics)
        return f"Memory saved (id: {entry_id})."

    # Ensure pyright recognizes decorator-registered functions as used
    _ = (memory_search, memory_get, memory_save)

    return toolset, _MEMORY_INSTRUCTIONS
