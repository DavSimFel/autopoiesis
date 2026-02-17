"""Unit tests for agent config, spawning, and queue dispatch."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from autopoiesis.agent.config import AgentConfig, load_agent_configs
from autopoiesis.agent.spawner import spawn_agent
from autopoiesis.infra.work_queue import dispatch_workitem, get_or_create_agent_queue, work_queue
from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

# ---------------------------------------------------------------------------
# TOML parsing
# ---------------------------------------------------------------------------


class TestLoadAgentConfigs:
    """TOML parsing: valid file, missing file, defaults merging."""

    def test_missing_file_returns_default(self, tmp_path: Path) -> None:
        configs = load_agent_configs(tmp_path / "nonexistent.toml")
        assert "default" in configs
        assert len(configs) == 1
        assert configs["default"].name == "default"
        assert configs["default"].role == "planner"

    def test_valid_toml(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "agents.toml"
        toml_path.write_text(
            """\
[defaults]
shell_tier = "review"

[agents.proxy]
role = "proxy"
model = "anthropic/claude-haiku-4"
tools = ["search", "topics"]
shell_tier = "free"
system_prompt = "knowledge/identity/proxy.md"

[agents.planner]
role = "planner"
model = "anthropic/claude-opus-4"
tools = ["shell", "search", "topics", "subscriptions"]
system_prompt = "knowledge/identity/planner.md"
"""
        )
        configs = load_agent_configs(toml_path)
        assert "proxy" in configs
        assert "planner" in configs
        assert configs["proxy"].shell_tier == "free"
        assert configs["planner"].shell_tier == "review"  # from defaults
        assert configs["proxy"].role == "proxy"
        assert configs["planner"].tools == ["shell", "search", "topics", "subscriptions"]

    def test_defaults_merging(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "agents.toml"
        toml_path.write_text(
            """\
[defaults]
shell_tier = "approve"
model = "anthropic/claude-haiku-4"

[agents.worker]
role = "executor"
tools = ["shell"]
system_prompt = "knowledge/identity/worker.md"
"""
        )
        configs = load_agent_configs(toml_path)
        worker = configs["worker"]
        assert worker.shell_tier == "approve"
        assert worker.model == "anthropic/claude-haiku-4"

    def test_empty_agents_section_returns_default(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "agents.toml"
        toml_path.write_text("[defaults]\nshell_tier = 'review'\n")
        configs = load_agent_configs(toml_path)
        assert "default" in configs

    def test_invalid_role_raises(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "agents.toml"
        toml_path.write_text(
            """\
[agents.bad]
role = "wizard"
tools = []
system_prompt = "x.md"
"""
        )
        with pytest.raises(ValueError, match="invalid role"):
            load_agent_configs(toml_path)

    def test_ephemeral_flag(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "agents.toml"
        toml_path.write_text(
            """\
[agents.runner]
role = "executor"
tools = ["shell"]
ephemeral = true
system_prompt = "knowledge/identity/runner.md"
"""
        )
        configs = load_agent_configs(toml_path)
        assert configs["runner"].ephemeral is True


# ---------------------------------------------------------------------------
# AgentConfig creation from spawn
# ---------------------------------------------------------------------------


class TestSpawnAgent:
    """Spawning creates correct config + workspace."""

    def test_spawn_creates_config(self, tmp_path: Path) -> None:
        old_home = os.environ.get("AUTOPOIESIS_HOME")
        os.environ["AUTOPOIESIS_HOME"] = str(tmp_path / ".autopoiesis")
        try:
            template = AgentConfig(
                name="executor",
                role="executor",
                model="anthropic/claude-sonnet-4",
                tools=["shell", "search"],
                shell_tier="review",
                system_prompt=Path("knowledge/identity/executor.md"),
            )
            spawned = spawn_agent(template, "fix-123", parent="planner")

            assert spawned.name == "executor-fix-123"
            assert spawned.ephemeral is True
            assert spawned.parent == "planner"
            assert spawned.role == "executor"
            assert spawned.model == template.model
            assert spawned.tools == ["shell", "search"]
        finally:
            if old_home is None:
                os.environ.pop("AUTOPOIESIS_HOME", None)
            else:
                os.environ["AUTOPOIESIS_HOME"] = old_home

    def test_spawn_creates_workspace_dirs(self, tmp_path: Path) -> None:
        old_home = os.environ.get("AUTOPOIESIS_HOME")
        os.environ["AUTOPOIESIS_HOME"] = str(tmp_path / ".autopoiesis")
        try:
            template = AgentConfig(
                name="executor",
                role="executor",
                model="anthropic/claude-sonnet-4",
                tools=["shell"],
                shell_tier="review",
                system_prompt=Path("knowledge/identity/executor.md"),
            )
            spawn_agent(template, "build-42", parent="planner")

            agent_dir = tmp_path / ".autopoiesis" / "agents" / "executor-build-42"
            assert (agent_dir / "workspace").is_dir()
            assert (agent_dir / "workspace" / "memory").is_dir()
            assert (agent_dir / "workspace" / "knowledge").is_dir()
            assert (agent_dir / "data").is_dir()
        finally:
            if old_home is None:
                os.environ.pop("AUTOPOIESIS_HOME", None)
            else:
                os.environ["AUTOPOIESIS_HOME"] = old_home


# ---------------------------------------------------------------------------
# Queue dispatch
# ---------------------------------------------------------------------------


class TestQueueDispatch:
    """Dispatch filters by agent_id."""

    def test_default_agent_uses_default_queue(self) -> None:
        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hello"),
            agent_id="default",
        )
        q = dispatch_workitem(item)
        assert q is work_queue

    def test_custom_agent_gets_own_queue(self) -> None:
        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hello"),
            agent_id="planner",
        )
        q = dispatch_workitem(item)
        assert q is not work_queue
        # Same agent_id should return the same queue
        q2 = get_or_create_agent_queue("planner")
        assert q is q2

    def test_topic_ref_on_workitem(self) -> None:
        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="work on topic"),
            agent_id="executor",
            topic_ref="my-task",
        )
        assert item.topic_ref == "my-task"

    def test_topic_ref_default_none(self) -> None:
        item = WorkItem(
            type=WorkItemType.CHAT,
            input=WorkItemInput(prompt="hello"),
        )
        assert item.topic_ref is None
