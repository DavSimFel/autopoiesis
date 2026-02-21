"""Tests for instance-based taint tracking."""

from __future__ import annotations

import pytest

from autopoiesis.security.taint_tracker import TaintTracker


def test_taint_tracker_instances_are_isolated() -> None:
    left = TaintTracker()
    right = TaintTracker()

    left.taint("user_input")
    assert left.is_tainted("user_input")
    assert not right.is_tainted("user_input")


def test_snapshot_is_immutable_and_no_public_clear() -> None:
    tracker = TaintTracker()
    tracker.taint_many(["a", "b"])
    snapshot = tracker.snapshot()

    assert snapshot == frozenset({"a", "b"})
    assert not hasattr(tracker, "clear")
    assert "add" not in dir(snapshot)


def test_empty_label_is_rejected() -> None:
    tracker = TaintTracker()
    with pytest.raises(ValueError, match="must not be empty"):
        tracker.taint("  ")
