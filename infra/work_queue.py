"""DBOS queue instances for background agent work.

Dependencies: dbos
Wired in: agent/worker.py → enqueue()
"""

try:
    from dbos import Queue
except ImportError as exc:
    missing_package = exc.name or "unknown package"
    raise SystemExit(
        f"Missing DBOS dependency `{missing_package}`. Run `uv sync` to install `dbos`."
    ) from exc

work_queue = Queue(
    "agent_work",
    priority_enabled=True,
    concurrency=1,
    polling_interval_sec=1.0,
)
