"""In-process stream handles for real-time work item output.

Stream handles are a convenience layer — they let callers receive tokens
as they are generated. They are NOT durable and NOT serialized to the queue.
Durability comes from the final WorkItemOutput persisted after completion.

Usage:
    handle = PrintStreamHandle()
    register_stream(work_item.id, handle)
    # ... worker picks up the handle, streams to it, unregisters when done
"""

from __future__ import annotations

import sys
from typing import Protocol


class StreamHandle(Protocol):
    """Protocol for receiving streamed agent output in real time."""

    def write(self, chunk: str) -> None:
        """Receive a chunk of streamed text."""
        ...

    def close(self) -> None:
        """Signal that streaming is complete."""
        ...


class PrintStreamHandle:
    """Stream handle that prints chunks to stdout in real time."""

    def write(self, chunk: str) -> None:
        print(chunk, end="", flush=True)

    def close(self) -> None:
        print(file=sys.stdout)


# In-process registry — keyed by work item id.
# NOT durable. Only works within the same process.
_stream_handles: dict[str, StreamHandle] = {}


def register_stream(work_item_id: str, handle: StreamHandle) -> None:
    """Register a stream handle for a work item. Must be same process as worker."""
    _stream_handles[work_item_id] = handle


def take_stream(work_item_id: str) -> StreamHandle | None:
    """Take (pop) a stream handle for a work item. Returns None if not registered."""
    return _stream_handles.pop(work_item_id, None)
