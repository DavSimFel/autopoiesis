"""DBOS queue instances for background agent work."""

try:
    from dbos import Queue
except ImportError as exc:
    raise SystemExit("DBOS not installed. Run: uv sync") from exc

work_queue = Queue(
    "agent_work",
    priority_enabled=True,
    concurrency=1,
    polling_interval_sec=1.0,
)
