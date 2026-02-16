"""Rich live display manager with per-section streaming channels.

Each channel represents one logical activity (tool call, reasoning, assistant
response) rendered as a branch in a Rich tree. Completed channels show a
one-line summary instead of disappearing.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Final

from streaming import ChannelStatus

try:
    from rich.console import Console
    from rich.live import Live
    from rich.text import Text
    from rich.tree import Tree
except ModuleNotFoundError as exc:
    missing_package = exc.name or "unknown package"
    raise SystemExit(
        f"Missing display dependency package `{missing_package}`. "
        "Run `uv sync` so `rich>=13.0` is installed."
    ) from exc

_SPINNER_FRAMES: Final[tuple[str, ...]] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧")
_DONE_ICON: Final[str] = "✔"
_ERROR_ICON: Final[str] = "✖"
_DEFAULT_TAIL: Final[int] = 5
_SUMMARY_MAX_LEN: Final[int] = 80
_REFRESH_PER_SEC: Final[int] = 4


@dataclass
class DisplayChannel:
    """In-memory state for one display section."""

    id: str
    label: str
    content: str = ""
    status: ChannelStatus = "running"
    summary: str | None = None
    pinned: bool = False
    order: int = 0


class RichDisplayManager:
    """Render multiple streaming channels in a single Rich live tree."""

    def __init__(
        self,
        *,
        console: Console | None = None,
        tail_lines: int = _DEFAULT_TAIL,
    ) -> None:
        """Initialize live display.

        Args:
            console: Optional Rich console instance.
            tail_lines: Recent lines shown for running channels.
        """
        if tail_lines < 1:
            raise ValueError("tail_lines must be >= 1")
        self._console = console or Console()
        self._tail = tail_lines
        self._channels: dict[str, DisplayChannel] = {}
        self._order_counter = 0
        self._lock = threading.RLock()
        self._closed = False
        self._live = Live(
            console=self._console,
            auto_refresh=True,
            refresh_per_second=_REFRESH_PER_SEC,
            transient=True,
            get_renderable=self._render_tree,
        )
        self._live.start()

    def create_channel(self, channel_id: str, label: str, *, pinned: bool = False) -> None:
        """Create or update a channel label.

        Args:
            channel_id: Stable channel identifier.
            label: Human-readable label.
            pinned: If True, always show full content (never summarize).
        """
        with self._lock:
            if self._closed:
                return
            existing = self._channels.get(channel_id)
            if existing is not None:
                existing.label = label
                existing.pinned = pinned
            else:
                self._channels[channel_id] = DisplayChannel(
                    id=channel_id,
                    label=label,
                    pinned=pinned,
                    order=self._order_counter,
                )
                self._order_counter += 1

    def update_channel(self, channel_id: str, content: str) -> None:
        """Append content to a channel.

        Args:
            channel_id: Existing or auto-created channel id.
            content: Text fragment to append.
        """
        if not content:
            return
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        with self._lock:
            if self._closed:
                return
            ch = self._channels.get(channel_id)
            if ch is None:
                ch = DisplayChannel(
                    id=channel_id,
                    label=channel_id,
                    order=self._order_counter,
                )
                self._order_counter += 1
                self._channels[channel_id] = ch
            ch.content += normalized

    def complete_channel(
        self,
        channel_id: str,
        status: ChannelStatus,
        summary: str | None = None,
    ) -> None:
        """Mark a channel finished with an optional one-line summary.

        Args:
            channel_id: Existing channel id.
            status: Final status.
            summary: Optional summary shown after completion. If None,
                     last non-empty line of content is used.
        """
        with self._lock:
            ch = self._channels.get(channel_id)
            if ch is None:
                return
            ch.status = status
            if summary is not None:
                ch.summary = summary
            elif not ch.pinned:
                ch.summary = self._auto_summary(ch.content)

    def close(self) -> None:
        """Stop live rendering and print final plain-text summary."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            channels = sorted(self._channels.values(), key=lambda c: c.order)
        self._live.stop()
        self._print_final(channels)

    def pause(self) -> None:
        """Temporarily stop live rendering (e.g. for input prompts)."""
        self._live.stop()

    def resume(self) -> None:
        """Resume live rendering after a pause."""
        with self._lock:
            if self._closed:
                return
        self._live.start()

    def channels_snapshot(self) -> dict[str, DisplayChannel]:
        """Return a shallow copy of channel state for diagnostics."""
        with self._lock:
            return dict(self._channels)

    # -- rendering -----------------------------------------------------------

    def _render_tree(self) -> Tree:
        with self._lock:
            channels = sorted(self._channels.values(), key=lambda c: c.order)
            frame = int(time.monotonic() * 10) % len(_SPINNER_FRAMES)
        root = Tree("")
        for ch in channels:
            icon = self._icon(ch.status, frame)
            label = f"{icon} {ch.label}"
            if ch.status != "running" and not ch.pinned:
                summary = ch.summary or ""
                if summary:
                    root.add(f"{label} — [dim]{self._truncate(summary)}[/dim]")
                else:
                    root.add(label)
            else:
                tail = self._tail_content(ch.content)
                if tail:
                    node = root.add(label)
                    node.add(Text(tail))
                else:
                    root.add(f"{label} [dim]…[/dim]")
        return root

    def _tail_content(self, content: str) -> str:
        if not content:
            return ""
        lines = content.splitlines()
        return "\n".join(lines[-self._tail :]) if lines else ""

    def _auto_summary(self, content: str) -> str:
        if not content:
            return ""
        for line in reversed(content.splitlines()):
            stripped = line.strip()
            if stripped:
                return self._truncate(stripped)
        return ""

    def _truncate(self, text: str) -> str:
        if len(text) <= _SUMMARY_MAX_LEN:
            return text
        return text[: _SUMMARY_MAX_LEN - 1] + "…"

    def _icon(self, status: ChannelStatus, frame: int) -> str:
        if status == "running":
            return f"[yellow]{_SPINNER_FRAMES[frame]}[/yellow]"
        if status == "done":
            return f"[green]{_DONE_ICON}[/green]"
        return f"[red]{_ERROR_ICON}[/red]"

    def _print_final(self, channels: list[DisplayChannel]) -> None:
        """Print plain-text output after Live stops for scrollback/logs."""
        for ch in channels:
            if ch.pinned and ch.content:
                self._console.print(ch.content, highlight=False)
            elif ch.status == "error":
                icon = _ERROR_ICON
                summary = ch.summary or ch.label
                self._console.print(f"  {icon} {ch.label} — {summary}", style="red")
