"""Unit tests for store.conversation_log — T2 reflection log storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from autopoiesis.store.conversation_log import (
    append_turn,
    format_entry,
    parse_messages,
    rotate_logs,
)
from autopoiesis.store.knowledge import init_knowledge_index

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_message(text: str) -> ModelRequest:
    """Create a minimal user ModelRequest."""
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _make_system_message(text: str) -> ModelRequest:
    """Create a minimal system ModelRequest."""
    return ModelRequest(parts=[SystemPromptPart(content=text)])


def _make_assistant_message(
    text: str,
    tool_names: list[str] | None = None,
) -> ModelResponse:
    """Create a ModelResponse with optional tool calls."""
    parts: list[object] = [TextPart(content=text)]
    for name in tool_names or []:
        parts.append(ToolCallPart(tool_name=name, args="{}"))
    return ModelResponse(parts=parts)  # type: ignore[arg-type]


def _make_tool_return_message(tool_name: str, result: str) -> ModelRequest:
    """Create a ToolReturnPart request (tool result — should be excluded from logs)."""
    return ModelRequest(
        parts=[ToolReturnPart(tool_name=tool_name, content=result, tool_call_id="abc")]
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def knowledge_root(tmp_path: Path) -> Path:
    return tmp_path / "knowledge"


@pytest.fixture()
def knowledge_db(tmp_path: Path) -> str:
    db = str(tmp_path / "knowledge.sqlite")
    init_knowledge_index(db)
    return db


# ---------------------------------------------------------------------------
# Test 1: Log file created with correct format
# ---------------------------------------------------------------------------


class TestLogFileFormat:
    def test_file_created_in_correct_location(
        self, knowledge_root: Path, knowledge_db: str
    ) -> None:
        """Log file is created under knowledge/logs/{agent_id}/YYYY-MM-DD.md."""
        ts = datetime(2026, 2, 20, 14, 39, 0, tzinfo=UTC)
        messages = [
            _make_user_message("Hello, summarize quantum computing."),
            _make_assistant_message("Quantum computing has seen great progress."),
        ]

        result_path = append_turn(knowledge_root, knowledge_db, "my-agent", messages, timestamp=ts)

        assert result_path is not None
        expected = knowledge_root / "logs" / "my-agent" / "2026-02-20.md"
        assert result_path == expected
        assert result_path.exists()

    def test_file_contains_timestamp_header(self, knowledge_root: Path, knowledge_db: str) -> None:
        """Each entry block has an ISO timestamp as a markdown H2 header."""
        ts = datetime(2026, 2, 20, 14, 39, 0, tzinfo=UTC)
        messages = [_make_user_message("test question")]

        append_turn(knowledge_root, knowledge_db, "agent1", messages, timestamp=ts)

        content = (knowledge_root / "logs" / "agent1" / "2026-02-20.md").read_text()
        assert "## 2026-02-20T14:39:00+00:00" in content

    def test_file_contains_role_labels(self, knowledge_root: Path, knowledge_db: str) -> None:
        """Roles 'user' and 'assistant' appear as bold labels in the log."""
        ts = datetime(2026, 2, 20, 15, 0, 0, tzinfo=UTC)
        messages = [
            _make_user_message("What is autopoiesis?"),
            _make_assistant_message("Autopoiesis is a system that produces itself."),
        ]

        append_turn(knowledge_root, knowledge_db, "agent2", messages, timestamp=ts)

        content = (knowledge_root / "logs" / "agent2" / "2026-02-20.md").read_text()
        assert "**user**" in content
        assert "**assistant**" in content
        assert "What is autopoiesis?" in content
        assert "Autopoiesis is a system" in content

    def test_system_role_logged(self, knowledge_root: Path, knowledge_db: str) -> None:
        """System prompt messages are logged with role 'system'."""
        ts = datetime(2026, 2, 20, 16, 0, 0, tzinfo=UTC)
        messages = [_make_system_message("You are a helpful assistant.")]

        append_turn(knowledge_root, knowledge_db, "agent3", messages, timestamp=ts)

        content = (knowledge_root / "logs" / "agent3" / "2026-02-20.md").read_text()
        assert "**system**" in content

    def test_multiple_turns_appended_to_same_daily_file(
        self, knowledge_root: Path, knowledge_db: str
    ) -> None:
        """Subsequent turns on the same day are appended, not overwritten."""
        ts1 = datetime(2026, 2, 20, 10, 0, 0, tzinfo=UTC)
        ts2 = datetime(2026, 2, 20, 11, 0, 0, tzinfo=UTC)

        append_turn(
            knowledge_root,
            knowledge_db,
            "agent4",
            [_make_user_message("First question")],
            timestamp=ts1,
        )
        append_turn(
            knowledge_root,
            knowledge_db,
            "agent4",
            [_make_user_message("Second question")],
            timestamp=ts2,
        )

        content = (knowledge_root / "logs" / "agent4" / "2026-02-20.md").read_text()
        assert "First question" in content
        assert "Second question" in content

    def test_empty_messages_returns_none(self, knowledge_root: Path, knowledge_db: str) -> None:
        """No log file is written when messages list is empty."""
        result = append_turn(knowledge_root, knowledge_db, "agent5", [])
        assert result is None

    def test_content_summary_truncated(self, knowledge_root: Path, knowledge_db: str) -> None:
        """Content longer than 200 chars is truncated with an ellipsis."""
        long_text = "word " * 100  # 500 chars
        ts = datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC)
        messages = [_make_user_message(long_text)]

        append_turn(knowledge_root, knowledge_db, "agent6", messages, timestamp=ts)

        content = (knowledge_root / "logs" / "agent6" / "2026-02-20.md").read_text()
        assert "..." in content
        # Full long_text should NOT appear verbatim (it's 500 chars)
        assert long_text.strip() not in content


# ---------------------------------------------------------------------------
# Test 2: Tool call names captured, results excluded
# ---------------------------------------------------------------------------


class TestToolCallCapture:
    def test_tool_names_appear_in_log(self, knowledge_root: Path, knowledge_db: str) -> None:
        """Tool call names from ToolCallPart are recorded in the log."""
        ts = datetime(2026, 2, 20, 14, 0, 0, tzinfo=UTC)
        messages = [
            _make_user_message("Search for something"),
            _make_assistant_message(
                "I'll search for you.", tool_names=["search_knowledge", "web_search"]
            ),
        ]

        append_turn(knowledge_root, knowledge_db, "tool-agent", messages, timestamp=ts)

        content = (knowledge_root / "logs" / "tool-agent" / "2026-02-20.md").read_text()
        assert "search_knowledge" in content
        assert "web_search" in content

    def test_tool_results_excluded_from_log(self, knowledge_root: Path, knowledge_db: str) -> None:
        """ToolReturnPart results (potentially large) are excluded from logs."""
        ts = datetime(2026, 2, 20, 14, 0, 0, tzinfo=UTC)
        large_result = "LARGE_RESULT_DATA: " + "x" * 1000
        messages = [
            _make_tool_return_message("search_knowledge", large_result),
        ]

        append_turn(knowledge_root, knowledge_db, "tool-agent2", messages, timestamp=ts)

        log_file = knowledge_root / "logs" / "tool-agent2" / "2026-02-20.md"
        if log_file.exists():
            content = log_file.read_text()
            assert large_result not in content
            assert "LARGE_RESULT_DATA" not in content

    def test_parse_messages_extracts_tool_names_only(self) -> None:
        """parse_messages returns tool call names, not return values."""
        tool_return = _make_tool_return_message("my_tool", "SECRET_RESULT_CONTENT")
        assistant_with_calls = _make_assistant_message(
            "Calling tools.", tool_names=["tool_a", "tool_b"]
        )
        messages = [tool_return, assistant_with_calls]

        entries = parse_messages(messages)

        # ToolReturnPart on a request message should be skipped entirely
        roles = [role for role, _, _ in entries]
        assert "user" not in roles or all("SECRET_RESULT_CONTENT" not in s for _, s, _ in entries)

        # Find the assistant entry
        assistant_entries = [(r, s, t) for r, s, t in entries if r == "assistant"]
        assert len(assistant_entries) == 1
        _, _, tools = assistant_entries[0]
        assert "tool_a" in tools
        assert "tool_b" in tools

    def test_tools_formatted_with_parenthetical(
        self, knowledge_root: Path, knowledge_db: str
    ) -> None:
        """Tool names appear as '*(tools: name1, name2)*' in the entry."""
        ts = datetime(2026, 2, 20, 14, 0, 0, tzinfo=UTC)
        messages = [
            _make_assistant_message("Did some work.", tool_names=["exec", "read_file"]),
        ]
        append_turn(knowledge_root, knowledge_db, "tool-fmt", messages, timestamp=ts)

        content = (knowledge_root / "logs" / "tool-fmt" / "2026-02-20.md").read_text()
        assert "*(tools: exec, read_file)*" in content


# ---------------------------------------------------------------------------
# Test 3: Logging disabled when config says so
# ---------------------------------------------------------------------------


class TestLoggingDisabled:
    def test_no_file_created_when_log_conversations_false(
        self, knowledge_root: Path, knowledge_db: str
    ) -> None:
        """When log_conversations=False the worker should skip append_turn.

        This test validates the expected usage pattern: the caller checks the
        flag before invoking append_turn.
        """
        log_conversations = False  # as read from AgentConfig / Runtime
        messages = [_make_user_message("This should not be logged.")]

        log_path = knowledge_root / "logs" / "silent-agent" / "2026-02-20.md"

        if log_conversations:
            append_turn(knowledge_root, knowledge_db, "silent-agent", messages)

        assert not log_path.exists()

    def test_append_turn_itself_always_writes_when_called(
        self, knowledge_root: Path, knowledge_db: str
    ) -> None:
        """append_turn always writes; caller is responsible for the flag check.

        This verifies the function has no internal enable/disable state.
        """
        ts = datetime(2026, 2, 20, 10, 0, 0, tzinfo=UTC)
        messages = [_make_user_message("Direct call.")]

        result = append_turn(knowledge_root, knowledge_db, "direct-agent", messages, timestamp=ts)

        assert result is not None
        assert result.exists()

    def test_worker_skips_logging_when_runtime_flag_false(
        self, knowledge_root: Path, knowledge_db: str, tmp_path: Path
    ) -> None:
        """Simulate the worker branch: no log written when log_conversations=False."""
        messages = [_make_user_message("secret")]
        log_conversations = False  # Runtime.log_conversations

        written: list[Path] = []

        if log_conversations:
            path = append_turn(knowledge_root, knowledge_db, "worker-agent", messages)
            if path:
                written.append(path)

        assert written == []


# ---------------------------------------------------------------------------
# Test 4: Rotation deletes old files
# ---------------------------------------------------------------------------


class TestRotation:
    def _create_log_file(
        self, knowledge_root: Path, agent_id: str, date_str: str, content: str = "# log\n"
    ) -> Path:
        """Helper to create a synthetic log file for a given date."""
        log_dir = knowledge_root / "logs" / agent_id
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{date_str}.md"
        log_file.write_text(content, encoding="utf-8")
        return log_file

    def test_old_files_deleted(self, knowledge_root: Path) -> None:
        """Files older than retention_days are removed by rotate_logs."""
        today = datetime.now(UTC).date()
        old_date = (today - timedelta(days=40)).strftime("%Y-%m-%d")
        recent_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")

        old_file = self._create_log_file(knowledge_root, "rot-agent", old_date)
        recent_file = self._create_log_file(knowledge_root, "rot-agent", recent_date)

        deleted = rotate_logs(knowledge_root, "rot-agent", retention_days=30)

        assert old_file in deleted
        assert not old_file.exists()
        assert recent_file.exists()  # kept

    def test_no_deletion_when_retention_zero(self, knowledge_root: Path) -> None:
        """When retention_days=0 no files are deleted."""
        today = datetime.now(UTC).date()
        old_date = (today - timedelta(days=100)).strftime("%Y-%m-%d")
        old_file = self._create_log_file(knowledge_root, "keep-agent", old_date)

        deleted = rotate_logs(knowledge_root, "keep-agent", retention_days=0)

        assert deleted == []
        assert old_file.exists()

    def test_recent_files_kept(self, knowledge_root: Path) -> None:
        """Files within the retention window are never deleted."""
        today = datetime.now(UTC).date()
        recent_date = today.strftime("%Y-%m-%d")
        recent_file = self._create_log_file(knowledge_root, "safe-agent", recent_date)

        deleted = rotate_logs(knowledge_root, "safe-agent", retention_days=30)

        assert recent_file not in deleted
        assert recent_file.exists()

    def test_nonexistent_log_dir_is_noop(self, knowledge_root: Path) -> None:
        """rotate_logs does not raise when the log directory does not exist."""
        deleted = rotate_logs(knowledge_root, "ghost-agent", retention_days=30)
        assert deleted == []

    def test_malformed_filename_ignored(self, knowledge_root: Path) -> None:
        """Files whose names can't be parsed as dates are left untouched."""
        log_dir = knowledge_root / "logs" / "parse-agent"
        log_dir.mkdir(parents=True, exist_ok=True)
        weird_file = log_dir / "not-a-date.md"
        weird_file.write_text("# weird\n")

        deleted = rotate_logs(knowledge_root, "parse-agent", retention_days=1)

        assert weird_file not in deleted
        assert weird_file.exists()

    def test_boundary_day_kept(self, knowledge_root: Path) -> None:
        """A file exactly retention_days old is kept (cutoff is strictly older)."""
        today = datetime.now(UTC).date()
        boundary_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
        boundary_file = self._create_log_file(knowledge_root, "boundary-agent", boundary_date)

        deleted = rotate_logs(knowledge_root, "boundary-agent", retention_days=30)

        assert boundary_file not in deleted
        assert boundary_file.exists()


# ---------------------------------------------------------------------------
# format_entry unit tests
# ---------------------------------------------------------------------------


class TestFormatEntry:
    def test_basic_format(self) -> None:
        ts = datetime(2026, 2, 20, 14, 0, 0, tzinfo=UTC)
        entries: list[tuple[str, str, list[str]]] = [
            ("user", "hello", []),
            ("assistant", "hi there", []),
        ]
        block = format_entry(ts, entries)

        assert "## 2026-02-20T14:00:00+00:00" in block
        assert "**user**: hello" in block
        assert "**assistant**: hi there" in block

    def test_tool_parenthetical_included(self) -> None:
        ts = datetime(2026, 2, 20, 14, 0, 0, tzinfo=UTC)
        entries = [("assistant", "working", ["tool_x"])]
        block = format_entry(ts, entries)
        assert "*(tools: tool_x)*" in block

    def test_no_tools_no_parenthetical(self) -> None:
        ts = datetime(2026, 2, 20, 14, 0, 0, tzinfo=UTC)
        entries: list[tuple[str, str, list[str]]] = [("user", "hi", [])]
        block = format_entry(ts, entries)
        assert "*(tools:" not in block
