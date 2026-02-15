"""DBOS queue instances for background agent work."""

from dbos import Queue

work_queue = Queue(
    "agent_work",
    priority_enabled=True,
    concurrency=1,
    polling_interval_sec=1.0,
)
