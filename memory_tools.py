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
    toolset: FunctionToolset[AgentDeps] = FunctionToolset()

    @toolset.tool
    async def memory_search(
        ctx: RunContext[AgentDeps],
        query: str,
        max_results: int = 5,
    ) -> str:
        """Search past conversations and memory files for relevant context.

        When to use: Before answering questions about prior work, decisions, preferences,
        or anything that might have been discussed in previous sessions. Also use when
        the user references something you don't have in current context.
        Returns: Ranked list of matching memory entries and file snippets with timestamps.
        Related: memory_save (to persist new knowledge), memory_get (to read full file content).

        Args:
            query: Natural language search query. FTS5 full-text search — use key terms
                rather than full sentences for best results.
            max_results: Number of results to return. Default 5.
        """
        return combined_search(db_path, workspace_root, query, max_results)

    @toolset.tool
    async def memory_get(
        ctx: RunContext[AgentDeps],
        path: str,
        from_line: int | None = None,
        lines: int | None = None,
    ) -> str:
        """Read lines from a memory file (MEMORY.md or memory/YYYY-MM-DD.md).

        When to use: After memory_search returns a file match and you need the full
        content, or when loading specific sections of long-term memory at session start.
        Returns: The requested lines from the file, or an error if the path is outside workspace.
        Related: memory_search (find relevant files first), memory_save (persist new entries).

        Args:
            path: Relative path within workspace (e.g., "MEMORY.md", "memory/2026-02-16.md").
            from_line: Starting line number (1-indexed). Omit to start from beginning.
            lines: Number of lines to read. Omit to read entire file.
        """
        return get_memory_file_snippet(workspace_root, path, from_line, lines)

    @toolset.tool
    async def memory_save(
        ctx: RunContext[AgentDeps],
        summary: str,
        topics: list[str],
    ) -> str:
        """Persist a piece of knowledge to the memory database for future sessions.

        When to use: When you learn something important that should survive across sessions —
        key decisions, user preferences, project context, lessons learned. Don't save
        routine or easily re-fetched information.
        Returns: Confirmation message with the new memory entry ID.
        Related: memory_search (retrieve saved memories later), memory_get (read memory files).

        Args:
            summary: The content to remember. Write it as a clear, self-contained statement
                that future-you can understand without additional context.
            topics: List of topic tags for categorization and search (e.g., ["project-x",
                "architecture", "decision"]). Use consistent, lowercase tag names.
        """
        entry_id = save_memory(db_path, summary, topics)
        return f"Memory saved (id: {entry_id})."

    # Ensure pyright recognizes decorator-registered functions as used
    _ = (memory_search, memory_get, memory_save)

    return toolset, _MEMORY_INSTRUCTIONS
