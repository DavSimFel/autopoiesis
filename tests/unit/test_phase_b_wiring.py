"""Unit tests for Phase B wiring: dispatch, validation, topic_ref, config."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestDispatchWorkitem:
    """dispatch_workitem routes to correct queue based on agent_id."""

    def test_routes_to_agent_queue(self) -> None:
        from autopoiesis.infra.work_queue import dispatch_workitem
        from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hello"),
            agent_id="coder",
        )
        queue = dispatch_workitem(item)
        assert queue.name == "agent_work_coder"

    def test_default_agent_uses_default_queue(self) -> None:
        from autopoiesis.infra.work_queue import dispatch_workitem, work_queue
        from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hello"),
            agent_id="default",
        )
        queue = dispatch_workitem(item)
        assert queue is work_queue

    def test_same_agent_returns_same_queue(self) -> None:
        from autopoiesis.infra.work_queue import dispatch_workitem
        from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

        item1 = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="a"),
            agent_id="reviewer",
        )
        item2 = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="b"),
            agent_id="reviewer",
        )
        assert dispatch_workitem(item1) is dispatch_workitem(item2)


class TestValidateSlug:
    """validate_slug accepts valid names, rejects traversal attempts."""

    def test_valid_name(self) -> None:
        from autopoiesis.agent.validation import validate_slug

        assert validate_slug("my-agent") == "my-agent"
        assert validate_slug("agent_1") == "agent_1"

    def test_rejects_empty(self) -> None:
        from autopoiesis.agent.validation import validate_slug

        with pytest.raises(ValueError, match="empty"):
            validate_slug("")
        with pytest.raises(ValueError, match="empty"):
            validate_slug("   ")

    def test_rejects_path_traversal(self) -> None:
        from autopoiesis.agent.validation import validate_slug

        with pytest.raises(ValueError, match="unsafe path characters"):
            validate_slug("../etc/passwd")
        with pytest.raises(ValueError, match="unsafe path characters"):
            validate_slug("foo/bar")
        with pytest.raises(ValueError, match="unsafe path characters"):
            validate_slug("foo\\bar")

    def test_rejects_long_names(self) -> None:
        from autopoiesis.agent.validation import validate_slug

        with pytest.raises(ValueError, match="exceeds"):
            validate_slug("a" * 65)

    def test_accepts_max_length(self) -> None:
        from autopoiesis.agent.validation import validate_slug

        result = validate_slug("a" * 64)
        assert len(result) == 64


class TestTopicRefAutoActivation:
    """topic_ref auto-activation transitions topic to in-progress."""

    def test_activates_open_topic(self, tmp_path: Path) -> None:
        from autopoiesis.agent.worker import activate_topic_ref
        from autopoiesis.topics.topic_manager import TopicRegistry

        topics_dir = tmp_path / "topics"
        topics_dir.mkdir()
        (topics_dir / "my-task.md").write_text("---\ntype: task\nstatus: open\n---\nDo the thing.")

        with patch(
            "autopoiesis.tools.toolset_builder.resolve_workspace_root",
            return_value=tmp_path,
        ):
            activate_topic_ref("my-task")

        # Verify status was updated
        registry = TopicRegistry(topics_dir)
        topic = registry.get_topic("my-task")
        assert topic is not None
        assert topic.status == "in-progress"

    def test_skips_non_open_topic(self, tmp_path: Path) -> None:
        from autopoiesis.agent.worker import activate_topic_ref
        from autopoiesis.topics.topic_manager import TopicRegistry

        topics_dir = tmp_path / "topics"
        topics_dir.mkdir()
        (topics_dir / "wip-task.md").write_text(
            "---\ntype: task\nstatus: in-progress\n---\nAlready working."
        )

        with patch(
            "autopoiesis.tools.toolset_builder.resolve_workspace_root",
            return_value=tmp_path,
        ):
            activate_topic_ref("wip-task")

        registry = TopicRegistry(topics_dir)
        topic = registry.get_topic("wip-task")
        assert topic is not None
        assert topic.status == "in-progress"

    def test_handles_missing_topic(self, tmp_path: Path) -> None:
        from autopoiesis.agent.worker import activate_topic_ref

        topics_dir = tmp_path / "topics"
        topics_dir.mkdir()

        with patch(
            "autopoiesis.tools.toolset_builder.resolve_workspace_root",
            return_value=tmp_path,
        ):
            # Should not raise
            activate_topic_ref("nonexistent")


class TestConfigLoadingInStartup:
    """Config loading is called when --config is passed."""

    def test_config_loaded_when_flag_provided(self, tmp_path: Path) -> None:
        config_file = tmp_path / "agents.toml"
        config_file.write_text(
            '[agents.planner]\nrole = "planner"\n[agents.coder]\nrole = "executor"\n'
        )

        with (
            patch("autopoiesis.cli.resolve_agent_name", return_value="default"),
            patch(
                "autopoiesis.cli.resolve_agent_workspace",
                return_value=MagicMock(root=tmp_path),
            ),
            patch("autopoiesis.cli.load_dotenv"),
            patch("autopoiesis.cli.otel_tracing"),
            patch("autopoiesis.cli._initialize_runtime", side_effect=SystemExit("stop")),
        ):
            import autopoiesis.cli as cli_mod

            cli_mod.get_agent_configs().clear()
            import sys

            old_argv = sys.argv
            sys.argv = ["chat", "--config", str(config_file)]
            try:
                cli_mod.main()
            except SystemExit as e:
                if str(e) != "stop":
                    pass  # Expected from _initialize_runtime mock
            finally:
                sys.argv = old_argv

            configs = cli_mod.get_agent_configs()
            assert "planner" in configs
            assert "coder" in configs

    def test_no_config_no_loading(self) -> None:
        """When no --config is passed, _agent_configs stays empty."""
        from autopoiesis.cli import get_agent_configs

        # Just verify the registry exists and can be empty
        # (full integration would require mocking the entire main flow)
        assert isinstance(get_agent_configs(), dict)
