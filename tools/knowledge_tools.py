"""PydanticAI tool definitions for file-based knowledge search.

Exposes a single ``search`` tool backed by FTS5 over knowledge files.
File read/write/edit uses the existing console toolset — no new tools needed.
"""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from models import AgentDeps
from store.knowledge import format_search_results, search_knowledge

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
Results are ranked by relevance.

### Writing knowledge
Use standard file tools (``write_file``, ``edit_file``) to manage knowledge files. \
Write daily notes to ``knowledge/journal/YYYY-MM-DD.md``. \
Distill insights into ``knowledge/memory/MEMORY.md`` periodically."""


def create_knowledge_toolset(
    knowledge_db_path: str,
) -> tuple[FunctionToolset[AgentDeps], str]:
    """Create the knowledge search toolset and return it with instructions."""
    toolset: FunctionToolset[AgentDeps] = FunctionToolset(
        docstring_format="google",
        require_parameter_descriptions=True,
    )
    meta: dict[str, str] = {"category": "knowledge"}

    @toolset.tool(metadata=meta)
    async def search(
        ctx: RunContext[AgentDeps],
        query: str,
        limit: int = 10,
    ) -> str:
        """Search the knowledge base for relevant information.

        Searches all indexed markdown files under knowledge/ using full-text
        search.  Returns ranked snippets with file paths and line numbers.

        Args:
            query: Natural language search query.
            limit: Maximum number of results to return. Default 10.
        """
        results = search_knowledge(knowledge_db_path, query, limit)
        return format_search_results(results)

    _ = (search,)

    return toolset, _KNOWLEDGE_INSTRUCTIONS
