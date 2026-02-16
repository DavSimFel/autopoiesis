"""Tests for ObservableToolset wrapper."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolset_wrappers import ObservableToolset, wrap_toolsets


@pytest.fixture
def mock_toolset() -> MagicMock:
    ts = MagicMock()
    ts.call_tool = AsyncMock(return_value="ok")
    return ts


async def test_observable_logs_success(
    mock_toolset: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    wrapper = ObservableToolset(mock_toolset)
    ctx = MagicMock()
    tool = MagicMock()
    with caplog.at_level(logging.INFO, logger="toolset_wrappers"):
        result = await wrapper.call_tool("my_tool", {}, ctx, tool)
    assert result == "ok"
    assert any("my_tool" in r.message and "status=ok" in r.message for r in caplog.records)


async def test_observable_logs_error(
    mock_toolset: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    mock_toolset.call_tool = AsyncMock(side_effect=RuntimeError("boom"))
    wrapper = ObservableToolset(mock_toolset)
    ctx = MagicMock()
    tool = MagicMock()
    with caplog.at_level(logging.ERROR, logger="toolset_wrappers"), pytest.raises(RuntimeError):
        await wrapper.call_tool("bad_tool", {}, ctx, tool)
    assert any("bad_tool" in r.message and "status=error" in r.message for r in caplog.records)


def test_wrap_toolsets_wraps_all() -> None:
    ts1 = MagicMock()
    ts2 = MagicMock()
    expected_count = 2
    wrapped = wrap_toolsets([ts1, ts2])
    assert len(wrapped) == expected_count
    assert all(isinstance(w, ObservableToolset) for w in wrapped)
