"""Worker end-to-end execution path integration tests.

Tests drive worker.py logic with realistic runtime wiring.
Mock only the LLM API (agent execution), not internal infrastructure.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from autopoiesis.models import (
    WorkItem,
    WorkItemInput,
    WorkItemOutput,
    WorkItemType,
)
from autopoiesis.store.history import (
    clear_checkpoint,
    init_history_store,
    load_checkpoint,
    save_checkpoint,
)
from autopoiesis.topics.topic_manager import TopicRegistry


class TestCheckpointRecovery:
    """Worker recovers from checkpoint when available."""

    def test_save_and_recover_checkpoint(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "history.sqlite")
        init_history_store(db_path)

        work_item_id = "test-item-001"
        history_json = '["msg1", "msg2"]'

        save_checkpoint(db_path, work_item_id, history_json, round_count=2)
        recovered = load_checkpoint(db_path, work_item_id)
        assert recovered == history_json

    def test_checkpoint_cleared_after_use(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "history.sqlite")
        init_history_store(db_path)

        save_checkpoint(db_path, "item-002", '["msg"]', round_count=1)
        clear_checkpoint(db_path, "item-002")
        assert load_checkpoint(db_path, "item-002") is None

    def test_missing_checkpoint_returns_none(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "history.sqlite")
        init_history_store(db_path)
        assert load_checkpoint(db_path, "nonexistent") is None


class TestTopicAutoActivation:
    """WorkItem with topic_ref auto-activates the topic."""

    def test_topic_ref_activates_open_topic(self, topics_dir: Path) -> None:
        from autopoiesis.agent.topic_activation import activate_topic_ref

        # Write topic with explicit open status in frontmatter
        (topics_dir / "fix-bug.md").write_text("---\ntype: task\nstatus: open\n---\nFix the bug.")
        registry = TopicRegistry(topics_dir)
        topic = registry.get_topic("fix-bug")
        assert topic is not None
        assert topic.status == "open"

        # Simulate activation by setting workspace root
        with patch(
            "autopoiesis.tools.toolset_builder.resolve_workspace_root",
            return_value=topics_dir.parent,
        ):
            activate_topic_ref("fix-bug")

        # Reload and check status
        registry2 = TopicRegistry(topics_dir)
        topic2 = registry2.get_topic("fix-bug")
        assert topic2 is not None
        assert topic2.status == "in-progress"

    def test_topic_ref_skips_non_open_topic(self, topics_dir: Path) -> None:
        from autopoiesis.agent.topic_activation import activate_topic_ref

        (topics_dir / "in-prog.md").write_text(
            "---\ntype: task\nstatus: in-progress\n---\nAlready working."
        )

        with patch(
            "autopoiesis.tools.toolset_builder.resolve_workspace_root",
            return_value=topics_dir.parent,
        ):
            activate_topic_ref("in-prog")

        registry = TopicRegistry(topics_dir)
        topic = registry.get_topic("in-prog")
        assert topic is not None
        assert topic.status == "in-progress"

    def test_missing_topic_ref_does_not_crash(self, topics_dir: Path) -> None:
        from autopoiesis.agent.topic_activation import activate_topic_ref

        with patch(
            "autopoiesis.tools.toolset_builder.resolve_workspace_root",
            return_value=topics_dir.parent,
        ):
            # Should not raise
            activate_topic_ref("nonexistent-topic")


class TestWorkItemDispatch:
    """WorkItem dispatch routes to correct agent queues."""

    def test_dispatch_creates_agent_queue(self) -> None:
        from autopoiesis.infra.work_queue import dispatch_workitem

        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hello"),
            agent_id="worker-test",
        )
        queue = dispatch_workitem(item)
        assert queue.name == "agent_work_worker-test"

    def test_dispatch_default_agent(self) -> None:
        from autopoiesis.infra.work_queue import dispatch_workitem

        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hello"),
            agent_id="default",
        )
        queue = dispatch_workitem(item)
        assert queue.name == "agent_work"


class TestWorkItemModelSerialization:
    """WorkItem model serializes and deserializes correctly for queue transport."""

    def test_round_trip(self) -> None:
        item = WorkItem(
            type=WorkItemType.CODE,
            input=WorkItemInput(prompt="write tests", message_history_json='[{"role":"user"}]'),
            agent_id="coder",
            topic_ref="fix-bug",
        )
        d = item.model_dump()
        recovered = WorkItem.model_validate(d)
        assert recovered.type == WorkItemType.CODE
        assert recovered.input.prompt == "write tests"
        assert recovered.agent_id == "coder"
        assert recovered.topic_ref == "fix-bug"
        assert recovered.input.message_history_json == '[{"role":"user"}]'

    def test_deferred_approval_fields(self) -> None:
        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(
                prompt=None,
                deferred_tool_results_json='{"approved": true}',
                approval_context_id="ctx-123",
            ),
        )
        d = item.model_dump()
        recovered = WorkItem.model_validate(d)
        assert recovered.input.prompt is None
        assert recovered.input.deferred_tool_results_json == '{"approved": true}'
        assert recovered.input.approval_context_id == "ctx-123"

    def test_output_deferred_vs_text(self) -> None:
        text_output = WorkItemOutput(text="done", message_history_json="[]")
        assert text_output.text == "done"
        assert text_output.deferred_tool_requests_json is None

        deferred_output = WorkItemOutput(
            deferred_tool_requests_json='{"requests": []}',
            message_history_json="[]",
        )
        assert deferred_output.text is None
        assert deferred_output.deferred_tool_requests_json is not None
