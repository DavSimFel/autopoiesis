"""Shared file-tail helpers for bounded log reads."""

from __future__ import annotations

import os
from pathlib import Path

_TAIL_BYTES_PER_LINE: int = 256


def read_tail_bytes(path: Path, max_bytes: int) -> bytes:
    """Read up to ``max_bytes`` from the end of ``path``."""
    if max_bytes <= 0:
        return b""
    try:
        with path.open("rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            if size == 0:
                return b""
            read_size = min(size, max_bytes)
            log_file.seek(-read_size, os.SEEK_END)
            return log_file.read(read_size)
    except OSError:
        return b""


def tail_lines(path: Path, n: int) -> list[str]:
    """Return the last ``n`` UTF-8-decoded lines from ``path``."""
    if n <= 0:
        return []
    data = read_tail_bytes(path, n * _TAIL_BYTES_PER_LINE)
    if not data:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-n:] if len(lines) > n else lines
