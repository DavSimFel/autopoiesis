"""Tests for the autopoiesis Harbor adapter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from autopoiesis_terminal_bench.agent import (
    AutopoiesisAgent,
    _collect_env,
    _load_result,
)


class TestCollectEnv:
    """Tests for _collect_env helper."""

    def test_forwards_present_keys(self) -> None:
        env = {"ANTHROPIC_API_KEY": "sk-test", "UNRELATED": "x"}
        with patch.dict("os.environ", env, clear=True):
            result = _collect_env()
        assert result == {"ANTHROPIC_API_KEY": "sk-test"}

    def test_empty_when_no_keys(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = _collect_env()
        assert result == {}


class TestLoadResult:
    """Tests for _load_result helper."""

    def test_valid_json(self, tmp_path: Path) -> None:
        data = {"success": True, "elapsed_seconds": 1.5}
        p = tmp_path / "result.json"
        p.write_text(json.dumps(data))
        assert _load_result(p) == data

    def test_invalid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "result.json"
        p.write_text("not json")
        assert _load_result(p) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "missing.json"
        assert _load_result(p) is None


class TestAutopoiesisAgent:
    """Tests for the agent adapter."""

    def test_name(self) -> None:
        assert AutopoiesisAgent.name() == "autopoiesis"

    def test_create_run_agent_commands(self, tmp_path: Path) -> None:
        agent = AutopoiesisAgent(logs_dir=tmp_path)
        cmds = agent.create_run_agent_commands("do something")
        assert len(cmds) == 2
        assert "mkdir" in cmds[0].command
        assert "chat.py run" in cmds[1].command
        assert "--task" in cmds[1].command
        assert "--output" in cmds[1].command

    def test_instruction_escaping(self, tmp_path: Path) -> None:
        agent = AutopoiesisAgent(logs_dir=tmp_path)
        cmds = agent.create_run_agent_commands('it\'s a "test"')
        run_cmd = cmds[1].command
        # Must not contain unescaped quotes
        assert "it's" not in run_cmd or "'" in run_cmd

    def test_populate_context_no_file(self, tmp_path: Path) -> None:
        from harbor.models.agent.context import AgentContext

        agent = AutopoiesisAgent(logs_dir=tmp_path)
        ctx = AgentContext()
        agent.populate_context_post_run(ctx)
        assert ctx.is_empty()

    def test_populate_context_with_result(self, tmp_path: Path) -> None:
        from harbor.models.agent.context import AgentContext

        result_file = tmp_path / "batch-result.json"
        result_file.write_text(
            json.dumps(
                {
                    "success": True,
                    "result": "done",
                    "error": None,
                    "approval_rounds": 2,
                    "elapsed_seconds": 10.5,
                }
            )
        )

        agent = AutopoiesisAgent(logs_dir=tmp_path)
        ctx = AgentContext()
        agent.populate_context_post_run(ctx)

        assert ctx.metadata is not None
        assert ctx.metadata["success"] is True
        assert ctx.metadata["approval_rounds"] == 2
        assert ctx.metadata["elapsed_seconds"] == 10.5
