"""Tests for agent.batch non-interactive batch mode."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.batch import BatchResult, format_output, run_batch


class TestFormatOutput:
    """Verify JSON serialization of BatchResult."""

    def test_success_output(self) -> None:
        result = BatchResult(
            success=True,
            result="hello world",
            error=None,
            approval_rounds=0,
            elapsed_seconds=1.234,
        )
        parsed = json.loads(format_output(result))
        assert parsed["success"] is True
        assert parsed["result"] == "hello world"
        assert parsed["error"] is None
        assert parsed["elapsed_seconds"] == 1.234

    def test_failure_output(self) -> None:
        result = BatchResult(
            success=False,
            result=None,
            error="something broke",
            approval_rounds=0,
            elapsed_seconds=0.5,
        )
        parsed = json.loads(format_output(result))
        assert parsed["success"] is False
        assert parsed["error"] == "something broke"


class TestRunBatchStdinRead:
    """Verify stdin task reading."""

    def test_empty_stdin_exits(self) -> None:
        with patch("agent.batch.sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "  "
            with pytest.raises(SystemExit, match="empty task"):
                run_batch(None)

    def test_dash_reads_stdin(self) -> None:
        with patch("agent.batch.sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "  "
            with pytest.raises(SystemExit, match="empty task"):
                run_batch("-")


class TestRunBatchIntegration:
    """Integration test with mocked runtime."""

    def test_success_writes_output_file(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from run_simple import SimpleResult

        mock_rt = MagicMock()
        mock_rt.backend = MagicMock()
        output_file = tmp_path / "result.json"

        fake_result = SimpleResult(text="done", all_messages=[], approval_rounds=1)

        with (
            patch("agent.batch.get_runtime", return_value=mock_rt),
            patch("agent.batch.run_simple", return_value=fake_result),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_batch("do something", output_path=str(output_file))

        assert exc_info.value.code == 0
        parsed = json.loads(output_file.read_text())
        assert parsed["success"] is True
        assert parsed["result"] == "done"
        assert parsed["approval_rounds"] == 1

    def test_failure_exit_code_1(self) -> None:
        from unittest.mock import MagicMock

        mock_rt = MagicMock()
        mock_rt.backend = MagicMock()

        with (
            patch("agent.batch.get_runtime", return_value=mock_rt),
            patch("agent.batch.run_simple", side_effect=RuntimeError("boom")),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_batch("do something")

        assert exc_info.value.code == 1

    def test_timeout_produces_error(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        mock_rt = MagicMock()
        mock_rt.backend = MagicMock()
        output_file = tmp_path / "result.json"

        def _slow_run(*_args: object, **_kwargs: object) -> None:
            raise TimeoutError("Batch run exceeded 1s timeout.")

        with (
            patch("agent.batch.get_runtime", return_value=mock_rt),
            patch("agent.batch.run_simple", side_effect=_slow_run),
            patch("agent.batch.signal.signal"),
            patch("agent.batch.signal.alarm"),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_batch("do something", output_path=str(output_file), timeout=1)

        assert exc_info.value.code == 1
        parsed = json.loads(output_file.read_text())
        assert parsed["success"] is False
        assert "timeout" in parsed["error"].lower()
