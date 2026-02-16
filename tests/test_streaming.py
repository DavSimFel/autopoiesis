"""Tests for streaming.py — stream handle registry and basic handles."""

from __future__ import annotations

from pytest import MonkeyPatch

from display.streaming import PrintStreamHandle, register_stream, take_stream


def test_register_and_take_stream() -> None:
    handle = PrintStreamHandle()
    register_stream("item-1", handle)
    taken = take_stream("item-1")
    assert taken is handle
    # Second take returns None (already consumed)
    assert take_stream("item-1") is None


def test_take_unregistered_returns_none() -> None:
    assert take_stream("nonexistent") is None


def test_print_stream_handle_write() -> None:
    import io
    import sys

    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        h = PrintStreamHandle()
        h.write("hello")
        h.write(" world")
        h.close()
    finally:
        sys.stdout = old
    assert "hello world" in buf.getvalue()


def test_rich_stream_handle_fallback_on_non_tty(monkeypatch: MonkeyPatch) -> None:
    """RichStreamHandle falls back to PrintStreamHandle on non-TTY."""
    import io
    import sys

    from display import streaming

    monkeypatch.setattr(streaming, "_is_tty", lambda: False)

    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        handle = streaming.RichStreamHandle()
        handle.write("test")
        handle.close()
    finally:
        sys.stdout = old

    assert "test" in buf.getvalue()


def test_rich_stream_handle_close_idempotent() -> None:
    from display.streaming import RichStreamHandle

    handle = RichStreamHandle()
    handle.close()
    handle.close()  # should not raise
