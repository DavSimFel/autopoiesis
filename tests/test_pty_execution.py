"""PTY execution tests for spawn/read behavior."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from unittest.mock import patch

import pytest

from pty_spawn import read_master, spawn_pty


async def _drain_master(master_fd: int) -> bytes:
    loop = asyncio.get_running_loop()
    chunks: list[bytes] = []
    while True:
        data = await loop.run_in_executor(None, read_master, master_fd)
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


@pytest.mark.asyncio()
async def test_spawn_pty_echo_hello() -> None:
    pty_proc = None
    try:
        pty_proc = await spawn_pty("echo hello")
    except OSError as exc:
        pytest.skip(f"PTY unavailable in test environment: {exc}")
    assert pty_proc is not None

    try:
        await asyncio.wait_for(pty_proc.process.wait(), timeout=5.0)
        output_bytes = await asyncio.wait_for(_drain_master(pty_proc.master_fd), timeout=5.0)
    finally:
        with suppress(OSError):
            os.close(pty_proc.master_fd)

    output = output_bytes.decode(errors="ignore")
    assert "hello" in output


@pytest.mark.asyncio()
async def test_spawn_pty_openpty_failure_is_raised() -> None:
    with (
        patch("pty_spawn.pty.openpty", side_effect=OSError("no pty support")),
        pytest.raises(OSError, match="no pty support"),
    ):
        await spawn_pty("echo hello")
