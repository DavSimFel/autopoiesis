"""Tests for agent spawn name validation."""

from __future__ import annotations

import pytest

from autopoiesis.agent.spawner import validate_agent_name


class TestValidateAgentName:
    """Validate validate_agent_name rejects unsafe names."""

    def test_simple_name(self) -> None:
        assert validate_agent_name("fix-bug-123") == "fix-bug-123"

    def test_underscores(self) -> None:
        assert validate_agent_name("my_task") == "my_task"

    def test_path_traversal_dotdot(self) -> None:
        with pytest.raises(ValueError, match="unsafe path characters"):
            validate_agent_name("../etc/passwd")

    def test_path_traversal_slash(self) -> None:
        with pytest.raises(ValueError, match="unsafe path characters"):
            validate_agent_name("foo/bar")

    def test_path_traversal_backslash(self) -> None:
        with pytest.raises(ValueError, match="unsafe path characters"):
            validate_agent_name("foo\\bar")

    def test_empty_name(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_agent_name("")

    def test_whitespace_only(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_agent_name("   ")

    def test_dotdot_embedded(self) -> None:
        with pytest.raises(ValueError, match="unsafe path characters"):
            validate_agent_name("task..name")

    def test_slugifies_spaces(self) -> None:
        assert validate_agent_name("my task") == "my-task"

    def test_slugifies_special_chars(self) -> None:
        assert validate_agent_name("task@name!") == "task-name-"
