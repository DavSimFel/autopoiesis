"""Low-level infrastructure and plumbing.

Public API: PtyProcess, cleanup_exec_logs,
    materialize_subscriptions, read_master, spawn_pty, work_queue
Internal: exec_registry, otel_tracing, pty_spawn, subscription_processor, work_queue
"""

from autopoiesis.infra.exec_registry import cleanup_exec_logs
from autopoiesis.infra.pty_spawn import PtyProcess, read_master, spawn_pty
from autopoiesis.infra.subscription_processor import materialize_subscriptions
from autopoiesis.infra.work_queue import work_queue

__all__ = [
    "PtyProcess",
    "cleanup_exec_logs",
    "materialize_subscriptions",
    "read_master",
    "spawn_pty",
    "work_queue",
]
