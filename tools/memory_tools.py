"""PydanticAI tool definitions for persistent chat memory.

Exposes memory_search, memory_get, and memory_save as agent tools backed
by the SQLite FTS5 memory store and workspace memory files.

Dependencies: models, store.memory
Wired in: toolset_builder.py → build_toolsets()
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from models import AgentDeps
from store.memory import combined_search, get_memory_file_snippet, save_memory

_MEMORY_INSTRUCTIONS = """\
## Persistent memory
You retain knowledge across sessions via memory tools.
- **Always search memory first** when asked about past work, decisions, preferences, or people.
- Save important outcomes, decisions with reasoning, and lessons learned.
- Keep MEMORY.md under 200 lines — distill, don't just append.
- Use `memory_search` for recall, `memory_get` for reading file snippets, \
`memory_save` for persisting new knowledge."""


def create_memory_toolset(
    db_path: str,
    workspace_root: Path,
) -> tuple[FunctionToolset[AgentDeps], str]:
    """Create memory tools and return the toolset with instructions."""
    toolset: FunctionToolset[AgentDeps] = FunctionToolset(
        docstring_format="google",
        require_parameter_descriptions=True,
    )
    mem_meta: dict[str, str] = {"category": "memory"}

    @toolset.tool(metadata=mem_meta)
    async def memory_search(
        ctx: RunContext[AgentDeps],
        query: str,
        max_results: int = 5,
    ) -> str:
        """Search past conversations, decisions, and saved context.

        Always call this before answering about prior work or preferences.

        Args:
            query: Natural language search query.
            max_results: Maximum results to return. Default 5.
        """
        return combined_search(db_path, workspace_root, query, max_results)

    @toolset.tool(metadata=mem_meta)
    async def memory_get(
        ctx: RunContext[AgentDeps],
        path: str,
        from_line: int | None = None,
        lines: int | None = None,
    ) -> str:
        """Read lines from a memory file (MEMORY.md or memory/*.md).

        Use after memory_search to pull full context from a match.

        Args:
            path: Relative path to the memory file (e.g. "MEMORY.md", "memory/2026-02-16.md").
            from_line: Starting line number (1-indexed). Omit to read from the beginning.
            lines: Number of lines to read. Omit to read to end of file.
        """
        return get_memory_file_snippet(workspace_root, path, from_line, lines)

    @toolset.tool(metadata=mem_meta)
    async def memory_save(
        ctx: RunContext[AgentDeps],
        summary: str,
        topics: list[str],
    ) -> str:
        """Persist an important fact, decision, or outcome for future recall.

        Use for anything worth remembering across sessions.

        Args:
            summary: What to remember — decision, lesson, preference.
            topics: Tags for categorization (e.g. ["auth", "decision"]).
        """
        entry_id = save_memory(db_path, summary, topics)
        return f"Memory saved (id: {entry_id})."

    # Ensure pyright recognizes decorator-registered functions as used
    _ = (memory_search, memory_get, memory_save)

    return toolset, _MEMORY_INSTRUCTIONS
