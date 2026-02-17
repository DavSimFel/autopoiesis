"""Terminal UI and streaming display.

Public API: ChannelStatus, RichStreamHandle, StreamHandle,
    ToolAwareStreamHandle, forward_stream_events, register_stream,
    take_stream
Internal: rich_display, stream_formatting, streaming
"""

from autopoiesis.display.stream_formatting import forward_stream_events
from autopoiesis.display.streaming import (
    ChannelStatus,
    RichStreamHandle,
    StreamHandle,
    ToolAwareStreamHandle,
    register_stream,
    take_stream,
)

__all__ = [
    "ChannelStatus",
    "RichStreamHandle",
    "StreamHandle",
    "ToolAwareStreamHandle",
    "forward_stream_events",
    "register_stream",
    "take_stream",
]
