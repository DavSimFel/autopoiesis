"""Concurrency tests for RichDisplayManager locking behavior."""

from __future__ import annotations

import threading

from rich_display import RichDisplayManager

_THREAD_COUNT = 8
_WRITES_PER_THREAD = 30


def test_concurrent_channel_updates_are_thread_safe() -> None:
    manager = RichDisplayManager(tail_lines=5)
    manager.create_channel("shared", "Shared")
    errors: list[Exception] = []

    def _writer(worker_id: int) -> None:
        try:
            for i in range(_WRITES_PER_THREAD):
                manager.update_channel("shared", f"{worker_id}:{i}\n")
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=_writer, args=(worker_id,)) for worker_id in range(_THREAD_COUNT)
    ]

    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5.0)
            assert not thread.is_alive()

        manager.complete_channel("shared", "done")
        assert errors == []

        channel = manager.channels_snapshot()["shared"]
        assert channel.status == "done"
        for worker_id in range(_THREAD_COUNT):
            for i in range(_WRITES_PER_THREAD):
                assert f"{worker_id}:{i}\n" in channel.content
    finally:
        manager.close()
