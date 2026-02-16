"""Tests for streaming.py — stream handle registry and basic handles."""

from __future__ import annotations

from streaming import PrintStreamHandle, register_stream, take_stream


def test_register_and_take_stream() -> None:
    handle = PrintStreamHandle()
    register_stream("item-1", handle)
    taken = take_stream("item-1")
    assert taken is handle
    # Second take returns None (already consumed)
    assert take_stream("item-1") is None


def test_take_unregistered_returns_none() -> None:
    assert take_stream("nonexistent") is None


def test_print_stream_handle_write(capsys: object) -> None:
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


def test_rich_stream_handle_fallback_on_non_tty() -> None:
    """RichStreamHandle falls back to PrintStreamHandle on non-TTY."""
    from streaming import RichStreamHandle

    handle = RichStreamHandle()
    # In test (non-TTY), _fallback should be set
    assert handle._fallback is not None  # pyright: ignore[reportPrivateUsage]
    handle.write("test")
    handle.close()


def test_rich_stream_handle_close_idempotent() -> None:
    from streaming import RichStreamHandle

    handle = RichStreamHandle()
    handle.close()
    handle.close()  # should not raise
