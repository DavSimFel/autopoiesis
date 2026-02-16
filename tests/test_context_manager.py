"""Tests for context_manager and tool_result_truncation modules."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)

from context_manager import CHARS_PER_TOKEN, compact_history, estimate_tokens
from tool_result_truncation import truncate_tool_results


def _make_request(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _make_response(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


class TestEstimateTokens:
    def test_empty(self) -> None:
        assert estimate_tokens("") == 1

    def test_short(self) -> None:
        assert estimate_tokens("hello") == 1

    def test_longer(self) -> None:
        input_len = 400
        expected = input_len // CHARS_PER_TOKEN
        assert estimate_tokens("a" * input_len) == expected


class TestCompactHistory:
    def test_under_threshold_unchanged(self) -> None:
        msgs: list[ModelMessage] = [_make_request("hi"), _make_response("hello")]
        result = compact_history(msgs, max_tokens=10000)
        assert result == msgs

    def test_over_threshold_compacts(self) -> None:
        big = "x" * 4000
        msgs: list[ModelMessage] = [
            _make_request(big) for _ in range(20)
        ]
        keep = 5
        result = compact_history(msgs, max_tokens=5000, keep_recent=keep)
        expected_len = keep + 1  # 1 summary + keep_recent
        assert len(result) == expected_len
        assert isinstance(result[0], ModelRequest)
        first_part = result[0].parts[0]
        assert isinstance(first_part, UserPromptPart)
        assert "Compacted" in first_part.content

    def test_few_messages_not_compacted(self) -> None:
        big = "x" * 4000
        msgs: list[ModelMessage] = [_make_request(big) for _ in range(3)]
        result = compact_history(msgs, max_tokens=100, keep_recent=5)
        assert result == msgs


class TestTruncateToolResults:
    def test_small_results_unchanged(self, tmp_path: Path) -> None:
        part = ToolReturnPart(
            tool_name="test", content="short", tool_call_id="c1"
        )
        msgs: list[ModelMessage] = [ModelRequest(parts=[part])]
        result = truncate_tool_results(msgs, tmp_path, max_chars=100)
        assert result == msgs

    def test_large_result_truncated(self, tmp_path: Path) -> None:
        big_content = "x" * 200
        part = ToolReturnPart(
            tool_name="test", content=big_content, tool_call_id="c2"
        )
        msgs: list[ModelMessage] = [ModelRequest(parts=[part])]
        result = truncate_tool_results(msgs, tmp_path, max_chars=50)

        assert len(result) == 1
        req = result[0]
        assert isinstance(req, ModelRequest)
        ret_part = req.parts[0]
        assert isinstance(ret_part, ToolReturnPart)
        assert isinstance(ret_part.content, str)
        assert len(ret_part.content) < len(big_content) + 200
        assert "Truncated" in ret_part.content

        log_file = tmp_path / ".tmp" / "tool-results" / "c2.log"
        assert log_file.exists()
        assert log_file.read_text() == big_content

    def test_non_string_content_unchanged(self, tmp_path: Path) -> None:
        part = ToolReturnPart(
            tool_name="test", content={"key": "value"}, tool_call_id="c3"
        )
        msgs: list[ModelMessage] = [ModelRequest(parts=[part])]
        result = truncate_tool_results(msgs, tmp_path, max_chars=5)
        assert result == msgs
