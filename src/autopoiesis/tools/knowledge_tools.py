"""PydanticAI tool definitions for file-based knowledge search.

Exposes a single ``search`` tool backed by FTS5 over knowledge files.
File read/write/edit uses the existing console toolset — no new tools needed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from autopoiesis.models import AgentDeps
from autopoiesis.store.knowledge import (
    format_search_results,
    known_types,
    search_knowledge,
)

_KNOWLEDGE_INSTRUCTIONS = """\
## Knowledge system
Your knowledge lives in markdown files under ``knowledge/``.

### Auto-loaded context (every turn)
- ``knowledge/identity/SOUL.md`` — who you are
- ``knowledge/identity/USER.md`` — who you're helping
- ``knowledge/identity/AGENTS.md`` — operational rules
- ``knowledge/identity/TOOLS.md`` — tool/integration notes
- ``knowledge/memory/MEMORY.md`` — long-term curated memory (keep under 200 lines)
- Today's journal entry (``knowledge/journal/YYYY-MM-DD.md``)

### Search
Use ``search(query)`` to find anything in the knowledge base. \
Results are ranked by relevance.  You can filter by type \
(fact, experience, preference, note, conversation, decision, contact, project) \
and by date (since parameter).

### Writing knowledge
Use standard file tools (``write_file``, ``edit_file``) to manage knowledge files. \
Write daily notes to ``knowledge/journal/YYYY-MM-DD.md``. \
Distill insights into ``knowledge/memory/MEMORY.md`` periodically."""


def create_knowledge_toolset(
    knowledge_db_path: str,
    knowledge_root: str | None = None,
) -> tuple[FunctionToolset[AgentDeps], str]:
    """Create the knowledge search toolset and return it with instructions."""
    toolset: FunctionToolset[AgentDeps] = FunctionToolset(
        docstring_format="google",
        require_parameter_descriptions=True,
    )
    meta: dict[str, str] = {"category": "knowledge"}

    _kr = Path(knowledge_root) if knowledge_root else None

    @toolset.tool(metadata=meta)
    async def search(
        ctx: RunContext[AgentDeps],
        query: str,
        limit: int = 10,
        type_filter: str | None = None,
        since: str | None = None,
    ) -> str:
        """Search the knowledge base for relevant information.

        Searches all indexed markdown files under knowledge/ using full-text
        search.  Returns ranked snippets with file paths and line numbers.

        Args:
            query: Natural language search query.
            limit: Maximum number of results to return. Default 10.
            type_filter: Filter by file type (e.g. fact, note, decision).
                Only files with matching frontmatter type are returned.
            since: ISO datetime string. Only return files created or
                modified on/after this date (e.g. "2026-01-01").
        """
        since_dt: datetime | None = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=UTC)
            except ValueError:
                return f"Invalid 'since' date format: {since}. Use ISO format."

        if type_filter and type_filter not in known_types():
            return f"Unknown type '{type_filter}'. Valid types: {', '.join(sorted(known_types()))}"

        results = search_knowledge(
            knowledge_db_path,
            query,
            limit,
            type_filter=type_filter,
            since=since_dt,
            knowledge_root=_kr,
        )
        return format_search_results(results)

    _ = (search,)

    return toolset, _KNOWLEDGE_INSTRUCTIONS
