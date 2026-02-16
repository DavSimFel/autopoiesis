"""Tests for rich_display.py — DisplayChannel logic and RichDisplayManager."""

from __future__ import annotations

from typing import Any

from rich_display import DisplayChannel, RichDisplayManager


def _channels(mgr: RichDisplayManager) -> dict[str, Any]:
    """Access internal channels dict (test helper)."""
    return mgr._channels  # pyright: ignore[reportPrivateUsage]


def test_display_channel_defaults() -> None:
    ch = DisplayChannel(id="t1", label="Test")
    assert ch.status == "running"
    assert ch.content == ""
    assert ch.summary is None
    assert ch.pinned is False


def test_create_and_update_channel() -> None:
    mgr = RichDisplayManager(tail_lines=3)
    try:
        mgr.create_channel("c1", "Chan 1")
        mgr.update_channel("c1", "hello ")
        mgr.update_channel("c1", "world")
        assert _channels(mgr)["c1"].content == "hello world"
    finally:
        mgr.close()


def test_complete_channel_sets_status() -> None:
    mgr = RichDisplayManager(tail_lines=3)
    try:
        mgr.create_channel("c1", "Chan 1")
        mgr.update_channel("c1", "line1\nline2\n")
        mgr.complete_channel("c1", "done", summary="ok")
        ch = _channels(mgr)["c1"]
        assert ch.status == "done"
        assert ch.summary == "ok"
    finally:
        mgr.close()


def test_complete_channel_auto_summary() -> None:
    mgr = RichDisplayManager(tail_lines=3)
    try:
        mgr.create_channel("c1", "Chan 1")
        mgr.update_channel("c1", "first\nsecond\n")
        mgr.complete_channel("c1", "done")
        assert _channels(mgr)["c1"].summary == "second"
    finally:
        mgr.close()


def test_close_is_idempotent() -> None:
    mgr = RichDisplayManager(tail_lines=3)
    mgr.close()
    mgr.close()  # should not raise


def test_update_after_close_is_noop() -> None:
    mgr = RichDisplayManager(tail_lines=3)
    mgr.close()
    mgr.update_channel("c1", "data")
    assert "c1" not in _channels(mgr)


def test_pause_resume() -> None:
    mgr = RichDisplayManager(tail_lines=3)
    try:
        mgr.pause()
        mgr.resume()
    finally:
        mgr.close()


def test_tail_lines_validation() -> None:
    import pytest

    with pytest.raises(ValueError, match="tail_lines"):
        RichDisplayManager(tail_lines=0)
