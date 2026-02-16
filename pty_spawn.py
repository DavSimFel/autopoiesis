"""Thin typed wrapper around stdlib pty for async subprocess spawning."""

from __future__ import annotations

import asyncio
import logging
import os
import pty
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PtyProcess:
    """A subprocess attached to a pseudo-terminal."""

    process: asyncio.subprocess.Process
    master_fd: int
    slave_fd: int | None


async def spawn_pty(
    command: str,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> PtyProcess:
    """Spawn *command* under a PTY via ``pty.openpty()``.

    Returns a ``PtyProcess`` with the asyncio subprocess and the master/slave
    file descriptors. The caller owns closing ``master_fd`` when done.
    """
    master_fd, slave_fd = pty.openpty()
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env=env,
        )
    except OSError as exc:
        logger.debug("PTY subprocess spawn failed with %s", type(exc).__name__, exc_info=exc)
        os.close(master_fd)
        os.close(slave_fd)
        raise
    # The slave fd is now owned by the child; close our copy.
    os.close(slave_fd)
    return PtyProcess(process=process, master_fd=master_fd, slave_fd=None)


def read_master(master_fd: int, size: int = 4096) -> bytes:
    """Non-blocking read from the PTY master fd. Returns b'' on EOF/error."""
    try:
        return os.read(master_fd, size)
    except OSError:
        return b""
