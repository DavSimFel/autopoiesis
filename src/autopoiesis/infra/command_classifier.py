"""Command classification for shell security layer (Issue #170)."""

from __future__ import annotations

import re
import shlex
from enum import Enum


class Tier(Enum):
    """Security tier for shell commands."""

    FREE = "free"
    REVIEW = "review"
    APPROVE = "approve"
    BLOCK = "block"


_TIER_ORDER = {Tier.FREE: 0, Tier.REVIEW: 1, Tier.APPROVE: 2, Tier.BLOCK: 3}

_FREE_COMMANDS: frozenset[str] = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "echo",
        "pwd",
        "grep",
        "find",
        "pytest",
        "ruff",
        "pyright",
        "true",
        "false",
        "date",
        "whoami",
        "which",
        "env",
        "printenv",
        "sort",
        "uniq",
        "diff",
        "seq",
        "tr",
        "cut",
        "awk",
        "sed",
        "tee",
        "less",
        "more",
        "file",
        "stat",
        "du",
        "df",
        "uname",
        "id",
        "basename",
        "dirname",
        "realpath",
        "readlink",
        "test",
        "sleep",
    }
)

_FREE_GIT: frozenset[str] = frozenset(
    {"status", "log", "diff", "branch", "show", "stash", "tag", "remote", "fetch"}
)
_REVIEW_GIT: frozenset[str] = frozenset(
    {"commit", "add", "reset", "rebase", "merge", "cherry-pick"}
)
_APPROVE_GIT: frozenset[str] = frozenset({"push", "force-push"})

_REVIEW_COMMANDS: frozenset[str] = frozenset({"pip", "pip3", "python", "python3", "tmux"})
_APPROVE_COMMANDS: frozenset[str] = frozenset(
    {
        "rm",
        "curl",
        "wget",
        "chmod",
        "chown",
        "chgrp",
        "mv",
        "cp",
        "mkfs",
        "dd",
        "mount",
        "umount",
        "kill",
        "killall",
    }
)
_BLOCK_COMMANDS: frozenset[str] = frozenset({"sudo", "su", "doas"})

_REDIRECT_OUTSIDE_RE = re.compile(r">\s*/")


def _classify_single(command: str) -> Tier:  # noqa: C901, PLR0911
    """Classify a single command (no chains)."""
    command = command.strip()
    if not command:
        return Tier.FREE

    if _REDIRECT_OUTSIDE_RE.search(command):
        return Tier.APPROVE

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    if not tokens:
        return Tier.FREE

    program = tokens[0].rsplit("/", 1)[-1]

    if program in _BLOCK_COMMANDS:
        return Tier.BLOCK
    if program in _APPROVE_COMMANDS:
        return Tier.APPROVE
    if program == "git" and len(tokens) > 1:
        sub = tokens[1]
        if sub in _APPROVE_GIT:
            return Tier.APPROVE
        if sub in _REVIEW_GIT:
            return Tier.REVIEW
        if sub in _FREE_GIT:
            return Tier.FREE
        return Tier.REVIEW
    if program in _REVIEW_COMMANDS:
        return Tier.REVIEW
    if program in _FREE_COMMANDS:
        return Tier.FREE
    return Tier.REVIEW


def _split_chains(command: str) -> list[str]:
    """Split command on shell chain operators."""
    parts: list[str] = []
    current = ""
    i = 0
    while i < len(command):
        c = command[i]
        if c == ";":
            parts.append(current)
            current = ""
            i += 1
        elif (c == "&" and i + 1 < len(command) and command[i + 1] == "&") or (
            c == "|" and i + 1 < len(command) and command[i + 1] == "|"
        ):
            parts.append(current)
            current = ""
            i += 2
        elif c == "|":
            parts.append(current)
            current = ""
            i += 1
        else:
            current += c
            i += 1
    if current:
        parts.append(current)
    return parts


def classify(command: str) -> Tier:
    """Classify a shell command string into a security tier."""
    parts = _split_chains(command)
    worst = Tier.FREE
    for part in parts:
        tier = _classify_single(part)
        if _TIER_ORDER[tier] > _TIER_ORDER[worst]:
            worst = tier
    return worst
