"""Migration from SQLite memory store to file-based knowledge."""

from __future__ import annotations

import logging
from contextlib import closing
from pathlib import Path

from autopoiesis.db import open_db

logger = logging.getLogger(__name__)


def migrate_memory_to_knowledge(
    memory_db_path: str,
    knowledge_root: Path,
) -> int:
    """Export SQLite memory entries to knowledge/memory/MEMORY.md.

    Idempotent: skips entries whose summary already appears in the file.
    Returns the number of *new* entries migrated.
    """
    memory_file = knowledge_root / "memory" / "MEMORY.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        with closing(open_db(Path(memory_db_path))) as conn:
            rows = conn.execute(
                "SELECT timestamp, summary, topics FROM memory_entries ORDER BY timestamp"
            ).fetchall()
    except Exception:
        logger.warning("Could not read memory entries from %s", memory_db_path)
        return 0

    if not rows:
        return 0

    existing_content = ""
    if memory_file.is_file():
        existing_content = memory_file.read_text(encoding="utf-8")

    # Filter out entries already present (idempotency check)
    new_rows = [r for r in rows if r["summary"] not in existing_content]
    if not new_rows:
        return 0

    lines: list[str] = []
    if existing_content.strip():
        lines.append(existing_content.rstrip())
        lines.append("")

    lines.append("## Migrated from SQLite")
    lines.append("")
    for row in new_rows:
        topics = row["topics"]
        tag = f" [{topics}]" if topics else ""
        lines.append(f"- [{row['timestamp']}]{tag} {row['summary']}")

    memory_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(new_rows)
