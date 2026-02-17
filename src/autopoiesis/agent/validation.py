"""Centralized name/slug validation for agent identifiers.

Dependencies: (none — leaf module)
Wired in: agent/spawner.py, cli.py, agent/config.py
"""

from __future__ import annotations

import re

_UNSAFE_PATTERN = re.compile(r"[/\\]|\.\.")
_MAX_SLUG_LENGTH = 64


def validate_slug(name: str) -> str:
    """Validate a slug-style name used for agent identifiers.

    Rejects empty strings, names containing path traversal sequences
    (``..``, ``/``, ``\\``), and names longer than 64 characters.

    Returns the stripped *name* on success, raises ``ValueError`` otherwise.
    """
    stripped = name.strip() if name else ""
    if not stripped:
        raise ValueError("Name must not be empty")
    if _UNSAFE_PATTERN.search(stripped):
        raise ValueError(f"Name contains unsafe path characters: {stripped!r}")
    if len(stripped) > _MAX_SLUG_LENGTH:
        raise ValueError(f"Name exceeds {_MAX_SLUG_LENGTH} characters: {len(stripped)}")
    return stripped
