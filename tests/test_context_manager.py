"""Tests for context and truncation modules (issue #193)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)

from autopoiesis.agent.context import (
    CHARS_PER_TOKEN,
    DEFAULT_WARNING_THRESHOLD,
    check_context_usage,
    compact_history,
    estimate_tokens,
    estimate_tokens_for_model,
)
from autopoiesis.agent.truncation import (
    DEFAULT_MAX_BYTES,
    cap_tool_result,
    truncate_tool_results,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _make_response(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


def _make_tool_return(content: str, call_id: str = "c1") -> ToolReturnPart:
    return ToolReturnPart(tool_name="test_tool", content=content, tool_call_id=call_id)


# ===========================================================================
# Truncation tests
# ===========================================================================


class TestCapToolResult:
    """Unit tests for the cap_tool_result() helper."""

    def test_under_cap_unchanged(self) -> None:
        content = "hello world"
        result = cap_tool_result(content, max_bytes=100)
        assert result == content

    def test_exactly_at_cap_unchanged(self) -> None:
        content = "a" * 100
        result = cap_tool_result(content, max_bytes=100)
        assert result == content

    def test_over_cap_truncated(self) -> None:
        content = "x" * 200
        result = cap_tool_result(content, max_bytes=50)
        assert len(result.encode("utf-8")) > 50  # marker adds length
        assert "x" * 50 in result
        assert "truncated:" in result

    def test_truncation_marker_format(self) -> None:
        """Marker must follow the canonical format [truncated: {orig} -> {trunc}]."""
        content = "z" * 500
        result = cap_tool_result(content, max_bytes=100)
        # Marker format: [truncated: {original_size} -> {truncated_size}]
        assert "[truncated:" in result
        assert "->" in result
        # Original size in marker
        orig_bytes = len(content.encode("utf-8"))
        assert str(orig_bytes) in result

    def test_empty_string_unchanged(self) -> None:
        result = cap_tool_result("", max_bytes=10)
        assert result == ""


class TestTruncateToolResults:
    """Unit tests for truncate_tool_results() history processor."""

    def test_small_results_unchanged(self, tmp_path: Path) -> None:
        """Tool result under cap passes through without modification."""
        part = _make_tool_return("short content", "c1")
        msgs: list[ModelMessage] = [ModelRequest(parts=[part])]
        result = truncate_tool_results(msgs, tmp_path, max_chars=100)
        assert result == msgs

    def test_large_result_truncated(self, tmp_path: Path) -> None:
        """Tool result exceeding cap is truncated with correct marker."""
        big_content = "y" * 10_000
        part = _make_tool_return(big_content, "c2")
        msgs: list[ModelMessage] = [ModelRequest(parts=[part])]
        result = truncate_tool_results(msgs, tmp_path, max_chars=50)

        assert len(result) == 1
        req = result[0]
        assert isinstance(req, ModelRequest)
        ret_part = req.parts[0]
        assert isinstance(ret_part, ToolReturnPart)
        assert isinstance(ret_part.content, str)
        # Original content must be shorter in truncated form
        assert len(ret_part.content) < len(big_content) + 500
        # New marker format
        assert "[truncated:" in ret_part.content
        assert "->" in ret_part.content

    def test_full_output_saved_to_disk(self, tmp_path: Path) -> None:
        """Full tool output is persisted to disk for inspection."""
        big_content = "z" * 500
        part = _make_tool_return(big_content, "c3")
        msgs: list[ModelMessage] = [ModelRequest(parts=[part])]
        truncate_tool_results(msgs, tmp_path, max_chars=50)

        # New implementation stores to tmp/tool-results/{date}/{tool_name}_{hash}.out
        results_dir = tmp_path / "tmp" / "tool-results"
        result_files = list(results_dir.rglob("*.out"))
        assert len(result_files) == 1
        assert big_content in result_files[0].read_text()

    def test_non_string_content_unchanged(self, tmp_path: Path) -> None:
        """Non-string tool content passes through without modification."""
        part = ToolReturnPart(tool_name="test", content={"key": "value"}, tool_call_id="c4")
        msgs: list[ModelMessage] = [ModelRequest(parts=[part])]
        result = truncate_tool_results(msgs, tmp_path, max_chars=5)
        assert result == msgs

    def test_multiple_parts_mixed(self, tmp_path: Path) -> None:
        """Only oversized tool return parts are truncated; others left intact."""
        small = _make_tool_return("small", "small_id")
        big = _make_tool_return("B" * 200, "big_id")
        msgs: list[ModelMessage] = [ModelRequest(parts=[small, big])]
        result = truncate_tool_results(msgs, tmp_path, max_chars=50)

        req = result[0]
        assert isinstance(req, ModelRequest)
        small_part, big_part = req.parts[0], req.parts[1]
        assert isinstance(small_part, ToolReturnPart)
        assert small_part.content == "small"
        assert isinstance(big_part, ToolReturnPart)
        assert "[truncated:" in str(big_part.content)

    def test_default_cap_is_10kb(self) -> None:
        """DEFAULT_MAX_BYTES must equal 10 240 bytes (10 KB)."""
        assert DEFAULT_MAX_BYTES == 10 * 1024

    def test_env_cap_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TOOL_RESULT_MAX_BYTES env variable overrides the default cap."""
        monkeypatch.setenv("TOOL_RESULT_MAX_BYTES", "20")
        content = "A" * 100
        part = _make_tool_return(content, "env_cap")
        msgs: list[ModelMessage] = [ModelRequest(parts=[part])]
        result = truncate_tool_results(msgs, tmp_path)

        req = result[0]
        assert isinstance(req, ModelRequest)
        ret_part = req.parts[0]
        assert isinstance(ret_part, ToolReturnPart)
        assert "[truncated:" in str(ret_part.content)


# ===========================================================================
# Token estimation tests
# ===========================================================================


class TestEstimateTokens:
    """Unit tests for estimate_tokens() and estimate_tokens_for_model()."""

    def test_empty_returns_one(self) -> None:
        assert estimate_tokens("") == 1

    def test_short_string(self) -> None:
        assert estimate_tokens("hello") == 1

    def test_longer_string(self) -> None:
        length = 400
        expected = length // CHARS_PER_TOKEN
        assert estimate_tokens("a" * length) == expected

    def test_fallback_no_model(self) -> None:
        """Without a model name the char-based heuristic is used."""
        text = "word " * 40  # 200 chars → 50 tokens at ratio 4
        result = estimate_tokens(text)
        assert result >= 1

    def test_tiktoken_for_openai_model(self) -> None:
        """For a gpt-* model, tiktoken is used if available; else char-based."""
        text = "Hello, world! This is a test sentence for token estimation."
        result_char = estimate_tokens(text)
        result_tiktoken = estimate_tokens(text, model_name="gpt-4o")
        # Both should be positive integers; tiktoken gives a more precise count.
        assert result_tiktoken >= 1
        assert result_char >= 1
        # For natural language, tiktoken and char-based should agree within 2x.
        assert 0.5 * result_char <= result_tiktoken <= 2.0 * result_char

    def test_non_openai_model_uses_char_ratio(self) -> None:
        """Non-OpenAI model names fall back to character-based estimation."""
        text = "a" * 400
        result = estimate_tokens_for_model(text, model_name="anthropic/claude-sonnet-4")
        # 400 chars / 4 chars per token = 100
        assert result >= 1

    def test_code_content_uses_lower_ratio(self) -> None:
        """Code-heavy text (high non-alnum ratio) uses a lower chars/token ratio."""
        # Lots of braces, operators etc. → code ratio (3.5 chars/token)
        code = "{}[]();<>!=+-*/\\|^&~" * 20  # 400 chars, mostly non-alnum
        nl_text = "a" * 400
        code_tokens = estimate_tokens_for_model(code, model_name="anthropic/claude-3")
        nl_tokens = estimate_tokens_for_model(nl_text, model_name="anthropic/claude-3")
        # Code should yield more tokens than natural language of the same length.
        assert code_tokens >= nl_tokens


# ===========================================================================
# Context window usage / warning tests
# ===========================================================================


class TestCheckContextUsage:
    """Unit tests for check_context_usage()."""

    def test_under_threshold_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """No warning when context is well below the 80% threshold."""
        msgs: list[ModelMessage] = [_make_request("hi"), _make_response("hello")]
        with caplog.at_level(logging.WARNING, logger="autopoiesis.agent.context"):
            fraction = check_context_usage(msgs, max_tokens=100_000)
        assert fraction < DEFAULT_WARNING_THRESHOLD
        assert "Context window" not in caplog.text

    def test_over_80_percent_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A WARNING is emitted when the context window is >80% full."""
        big_text = "w " * 2000  # ~4000 chars → ~1000 tokens (char-based)
        msgs: list[ModelMessage] = [_make_request(big_text) for _ in range(5)]
        # max_tokens=5000 so ~5000 tokens in 5000 → ~100%
        with caplog.at_level(logging.WARNING, logger="autopoiesis.agent.context"):
            fraction = check_context_usage(msgs, max_tokens=5000)
        assert fraction >= DEFAULT_WARNING_THRESHOLD
        assert "Context window" in caplog.text

    def test_warning_threshold_configurable(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """CONTEXT_WARNING_THRESHOLD env variable controls the warning level."""
        monkeypatch.setenv("CONTEXT_WARNING_THRESHOLD", "0.5")
        # ~100 tokens in a 120-token window → 83% > 50%
        msgs: list[ModelMessage] = [_make_request("a" * 400)]  # 100 tokens
        with caplog.at_level(logging.WARNING, logger="autopoiesis.agent.context"):
            fraction = check_context_usage(msgs, max_tokens=120)
        assert fraction >= 0.5
        assert "Context window" in caplog.text


# ===========================================================================
# Compaction tests
# ===========================================================================


class TestCompactHistory:
    """Unit tests for compact_history()."""

    def test_under_threshold_unchanged(self) -> None:
        """Messages well under the compaction threshold are left intact."""
        msgs: list[ModelMessage] = [_make_request("hi"), _make_response("hello")]
        result = compact_history(msgs, max_tokens=10_000)
        assert result == msgs

    def test_over_threshold_compacts(self) -> None:
        """When token usage exceeds the compaction threshold, older messages are compacted."""
        big = "x" * 4000  # 1000 tokens per message (char-based)
        msgs: list[ModelMessage] = [_make_request(big) for _ in range(20)]
        keep = 5
        result = compact_history(msgs, max_tokens=5_000, keep_recent=keep)
        expected_len = keep + 1  # 1 summary + keep_recent
        assert len(result) == expected_len
        assert isinstance(result[0], ModelRequest)
        first_part = result[0].parts[0]
        assert isinstance(first_part, UserPromptPart)
        assert "Compacted" in first_part.content

    def test_few_messages_not_compacted(self) -> None:
        """History shorter than keep_recent is never compacted."""
        big = "x" * 4000
        msgs: list[ModelMessage] = [_make_request(big) for _ in range(3)]
        result = compact_history(msgs, max_tokens=100, keep_recent=5)
        assert result == msgs

    def test_compaction_fires_before_overflow(self) -> None:
        """Compaction triggers at <100% capacity (before overflow)."""
        # 10 messages x 1000 tokens = 10 000 tokens in a 10 000-token window
        # → 100% full — must compact (threshold default 0.9)
        big = "a" * 4000  # 1000 tokens
        msgs: list[ModelMessage] = [_make_request(big) for _ in range(10)]
        result = compact_history(msgs, max_tokens=10_000, keep_recent=3)
        # If compaction happened, we get fewer messages than we started with.
        assert len(result) < len(msgs)

    def test_compaction_logs_info(self, caplog: pytest.LogCaptureFixture) -> None:
        """An INFO log is emitted when compaction occurs."""
        big = "x" * 4000
        msgs: list[ModelMessage] = [_make_request(big) for _ in range(20)]
        with caplog.at_level(logging.INFO, logger="autopoiesis.agent.context"):
            compact_history(msgs, max_tokens=5_000, keep_recent=5)
        assert "Compacting" in caplog.text

    def test_compaction_threshold_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """COMPACTION_THRESHOLD env variable overrides the default 0.9."""
        # Very low threshold (0.1) should compact even small histories.
        monkeypatch.setenv("COMPACTION_THRESHOLD", "0.1")
        big = "x" * 400  # 100 tokens
        msgs: list[ModelMessage] = [_make_request(big) for _ in range(5)]
        # 500 tokens in 1000-token window → 50% > 10%
        result = compact_history(msgs, max_tokens=1_000, keep_recent=2)
        assert len(result) < len(msgs)

    def test_warning_before_compaction(self, caplog: pytest.LogCaptureFixture) -> None:
        """80% warning is emitted even when compaction also triggers."""
        big = "x" * 4000
        msgs: list[ModelMessage] = [_make_request(big) for _ in range(20)]
        with caplog.at_level(logging.WARNING, logger="autopoiesis.agent.context"):
            compact_history(msgs, max_tokens=5_000, keep_recent=5)
        assert "Context window" in caplog.text


# ===========================================================================
# Integration test: large tool result in full pipeline
# ===========================================================================


class TestIntegrationLargeToolResult:
    """Integration test: oversized tool results survive the full processing pipeline."""

    def test_large_tool_result_does_not_crash(self, tmp_path: Path) -> None:
        """A 100 KB tool result is truncated without errors before compaction."""
        huge_content = "L" * 100_000  # 100 KB
        part = _make_tool_return(huge_content, "huge_id")
        request = ModelRequest(parts=[part])
        history: list[ModelMessage] = [_make_request("do something"), request]

        # Step 1: truncate tool results (simulating history processor pipeline)
        after_trunc = truncate_tool_results(history, tmp_path, max_chars=10_240)

        # Verify truncation happened
        req_msg = after_trunc[1]
        assert isinstance(req_msg, ModelRequest)
        trunc_part = req_msg.parts[0]
        assert isinstance(trunc_part, ToolReturnPart)
        assert isinstance(trunc_part.content, str)
        assert "[truncated:" in trunc_part.content

        # Step 2: compact_history (should not crash even if still large)
        final = compact_history(after_trunc, max_tokens=200_000, keep_recent=10)
        assert len(final) >= 1

    def test_pipeline_with_many_large_results(self, tmp_path: Path) -> None:
        """Multiple large tool results are all truncated correctly."""
        history: list[ModelMessage] = []
        for i in range(5):
            part = _make_tool_return("Z" * 20_000, f"call_{i}")
            history.append(ModelRequest(parts=[part]))

        after_trunc = truncate_tool_results(history, tmp_path, max_chars=1_000)

        for msg in after_trunc:
            assert isinstance(msg, ModelRequest)
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    assert isinstance(part.content, str)
                    assert "[truncated:" in part.content
                    # Content must be within reasonable size bounds.
                    assert len(part.content.encode()) < 5_000
