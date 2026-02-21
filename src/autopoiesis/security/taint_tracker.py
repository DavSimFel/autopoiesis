"""Instance-based taint tracking for untrusted values."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from threading import Lock


def _normalize_label(label: str) -> str:
    normalized = label.strip()
    if not normalized:
        raise ValueError("Taint label must not be empty.")
    return normalized


@dataclass
class TaintTracker:
    """Track tainted labels with thread-safe, copy-only read access."""

    _tainted: set[str] = field(default_factory=lambda: set[str](), init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def taint(self, label: str) -> None:
        """Mark *label* as tainted."""
        normalized = _normalize_label(label)
        with self._lock:
            self._tainted.add(normalized)

    def taint_many(self, labels: Iterable[str]) -> None:
        """Mark multiple labels as tainted."""
        normalized = [_normalize_label(label) for label in labels]
        with self._lock:
            self._tainted.update(normalized)

    def is_tainted(self, label: str) -> bool:
        """Return whether *label* has been marked tainted."""
        normalized = _normalize_label(label)
        with self._lock:
            return normalized in self._tainted

    def snapshot(self) -> frozenset[str]:
        """Return an immutable snapshot of tainted labels."""
        with self._lock:
            return frozenset(self._tainted)
