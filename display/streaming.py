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
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from display.rich_display import RichDisplayManager

ChannelStatus = Literal["running", "done", "error"]


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
        """Write chunk to stdout."""
        print(chunk, end="", flush=True)

    def close(self) -> None:
        """Print trailing newline."""
        print(file=sys.stdout)


@runtime_checkable
class ToolAwareStreamHandle(StreamHandle, Protocol):
    """Optional extension for tool call and reasoning lifecycle events."""

    def start_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        details: str | None = None,
    ) -> None:
        """Signal that a tool call has started."""
        ...

    def finish_tool_call(
        self,
        tool_call_id: str,
        status: ChannelStatus,
        details: str | None = None,
    ) -> None:
        """Signal that a tool call has finished."""
        ...

    def start_thinking(self) -> None:
        """Signal that reasoning/thinking output has started."""
        ...

    def update_thinking(self, chunk: str) -> None:
        """Append a chunk of thinking content."""
        ...

    def finish_thinking(self) -> None:
        """Signal that reasoning/thinking is complete."""
        ...

    def pause_display(self) -> None:
        """Pause live rendering for interactive prompts."""
        ...

    def resume_display(self) -> None:
        """Resume live rendering after interactive prompts."""
        ...


def _is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


class RichStreamHandle:
    """Stream handle routing assistant output and tools to Rich live UI.

    Falls back to PrintStreamHandle on non-TTY outputs.
    """

    def __init__(
        self,
        *,
        display: RichDisplayManager | None = None,
    ) -> None:
        """Initialize rich stream routing.

        Args:
            display: Optional existing display manager to reuse.
        """
        if not _is_tty() and display is None:
            self._fallback: PrintStreamHandle | None = PrintStreamHandle()
            self._display: RichDisplayManager | None = None
            self._owns_display = False
        else:
            self._fallback = None
            if display is not None:
                self._display = display
                self._owns_display = False
            else:
                from display.rich_display import RichDisplayManager

                self._display = RichDisplayManager()
                self._owns_display = True
        self._main_id = "assistant"
        self._thinking_id = "thinking"
        self._tool_ids: dict[str, str] = {}
        self._closed = False
        if self._display is not None:
            self._display.create_channel(self._main_id, "🤖 Response", pinned=True)

    def write(self, chunk: str) -> None:
        """Append assistant stream chunks."""
        if self._fallback is not None:
            self._fallback.write(chunk)
            return
        if self._display is not None:
            self._display.update_channel(self._main_id, chunk)

    def close(self) -> None:
        """Mark response complete and stop owned display."""
        if self._closed:
            return
        self._closed = True
        if self._fallback is not None:
            self._fallback.close()
            return
        if self._display is not None:
            self._display.complete_channel(self._main_id, "done")
            if self._owns_display:
                self._display.close()

    def start_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        details: str | None = None,
    ) -> None:
        """Create a channel for a tool call."""
        if self._display is None:
            return
        cid = self._tool_ids.setdefault(tool_call_id, f"tool:{tool_call_id}")
        self._display.create_channel(cid, f"🔧 {tool_name}")
        if details:
            self._display.update_channel(cid, f"{details}\n")

    def finish_tool_call(
        self,
        tool_call_id: str,
        status: ChannelStatus,
        details: str | None = None,
    ) -> None:
        """Complete a tool-call channel with summary."""
        if self._display is None:
            return
        cid = self._tool_ids.get(tool_call_id, f"tool:{tool_call_id}")
        summary = _one_line(details) if details else None
        self._display.complete_channel(cid, status, summary=summary)

    def start_thinking(self) -> None:
        """Open a reasoning/thinking channel."""
        if self._display is None:
            return
        self._display.create_channel(self._thinking_id, "💭 Thinking")

    def update_thinking(self, chunk: str) -> None:
        """Append thinking content."""
        if self._display is None:
            return
        self._display.update_channel(self._thinking_id, chunk)

    def finish_thinking(self) -> None:
        """Collapse thinking channel."""
        if self._display is None:
            return
        self._display.complete_channel(self._thinking_id, "done")

    def show_approval(self, summary: str, status: ChannelStatus) -> None:
        """Create a collapsed approval channel with a one-line summary."""
        if self._display is not None:
            self._display.create_channel("approval", "🔒 Approval")
            self._display.complete_channel("approval", status, summary=summary)

    def pause_display(self) -> None:
        """Pause live rendering for approval prompts."""
        if self._display is not None:
            self._display.pause()

    def resume_display(self) -> None:
        """Resume live rendering after approval prompts."""
        if self._display is not None:
            self._display.resume()


def _one_line(text: str) -> str:
    """Extract first non-empty line from text."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


# In-process registry — keyed by work item id.
# NOT durable. Only works within the same process.
_stream_handles: dict[str, StreamHandle] = {}


def register_stream(work_item_id: str, handle: StreamHandle) -> None:
    """Register a stream handle for a work item. Must be same process as worker."""
    _stream_handles[work_item_id] = handle


def take_stream(work_item_id: str) -> StreamHandle | None:
    """Take (pop) a stream handle for a work item. Returns None if not registered."""
    return _stream_handles.pop(work_item_id, None)
