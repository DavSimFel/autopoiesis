"""DBOS queue instances for background agent work.

Dependencies: dbos, models
Wired in: agent/worker.py → enqueue()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

try:
    from dbos import Queue
except ImportError as exc:
    missing_package = exc.name or "unknown package"
    raise SystemExit(
        f"Missing DBOS dependency `{missing_package}`. Run `uv sync` to install `dbos`."
    ) from exc

if TYPE_CHECKING:
    from autopoiesis.models import WorkItem

work_queue = Queue(
    "agent_work",
    priority_enabled=True,
    concurrency=1,
    polling_interval_sec=1.0,
)

# ---------------------------------------------------------------------------
# Multi-agent dispatch
# ---------------------------------------------------------------------------

# Registry of per-agent queues.  The default ``work_queue`` above is always
# registered under ``"default"``.
_agent_queues: dict[str, Queue] = {"default": work_queue}


def get_or_create_agent_queue(agent_id: str) -> Queue:
    """Return the DBOS queue for *agent_id*, creating one if needed.

    All agents currently share the same underlying DBOS instance but get
    logically separate ``Queue`` objects so dispatch can target a specific
    agent's queue.
    """
    if agent_id in _agent_queues:
        return _agent_queues[agent_id]
    q = Queue(
        f"agent_work_{agent_id}",
        priority_enabled=True,
        concurrency=1,
        polling_interval_sec=1.0,
    )
    _agent_queues[agent_id] = q
    return q


def dispatch_workitem(item: WorkItem) -> Queue:
    """Route a WorkItem to the correct agent queue by ``agent_id``.

    Returns the queue the item should be enqueued on.
    """
    return get_or_create_agent_queue(item.agent_id)
