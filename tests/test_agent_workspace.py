"""Tests for agent identity and workspace path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopoiesis.agent.workspace import resolve_agent_name, resolve_agent_workspace


class TestResolveAgentName:
    """Tests for resolve_agent_name()."""

    def test_default_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTOPOIESIS_AGENT", raising=False)
        assert resolve_agent_name() == "default"

    def test_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOPOIESIS_AGENT", "prod")
        assert resolve_agent_name() == "prod"

    def test_cli_flag_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOPOIESIS_AGENT", "prod")
        assert resolve_agent_name("staging") == "staging"

    def test_cli_flag_none_falls_to_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOPOIESIS_AGENT", "prod")
        assert resolve_agent_name(None) == "prod"


class TestResolveAgentWorkspace:
    """Tests for resolve_agent_workspace()."""

    def test_default_paths(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTOPOIESIS_AGENT", raising=False)
        monkeypatch.delenv("AUTOPOIESIS_HOME", raising=False)
        paths = resolve_agent_workspace("default")
        home = Path("~/.autopoiesis").expanduser()
        assert paths.root == home / "agents" / "default"
        assert paths.workspace == paths.root / "workspace"
        assert paths.memory == paths.root / "workspace" / "memory"
        assert paths.skills == paths.root / "workspace" / "skills"
        assert paths.knowledge == paths.root / "workspace" / "knowledge"
        assert paths.tmp == paths.root / "workspace" / "tmp"
        assert paths.data == paths.root / "data"
        assert paths.keys == paths.root / "keys"

    def test_custom_agent_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTOPOIESIS_HOME", raising=False)
        paths = resolve_agent_workspace("foo")
        home = Path("~/.autopoiesis").expanduser()
        assert paths.root == home / "agents" / "foo"

    def test_agent_flag_resolves_to_agents_subdir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTOPOIESIS_HOME", raising=False)
        paths = resolve_agent_workspace("foo")
        assert "agents/foo" in str(paths.root)

    def test_env_var_resolves_same_as_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOPOIESIS_AGENT", "bar")
        monkeypatch.delenv("AUTOPOIESIS_HOME", raising=False)
        from_env = resolve_agent_workspace()
        from_flag = resolve_agent_workspace("bar")
        assert from_env == from_flag

    def test_two_agents_different_paths(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTOPOIESIS_HOME", raising=False)
        a = resolve_agent_workspace("alpha")
        b = resolve_agent_workspace("beta")
        assert a.root != b.root
        assert a.workspace != b.workspace
        assert a.data != b.data
        assert a.keys != b.keys

    def test_custom_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("AUTOPOIESIS_HOME", str(tmp_path))
        paths = resolve_agent_workspace("test")
        assert paths.root == tmp_path / "agents" / "test"

    def test_frozen_dataclass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTOPOIESIS_HOME", raising=False)
        paths = resolve_agent_workspace("default")
        with pytest.raises(AttributeError):
            paths.root = Path("/tmp/hack")  # type: ignore[misc]


class TestAgentIdOnWorkItem:
    """Tests for the agent_id field on WorkItem."""

    def test_default_agent_id(self) -> None:
        from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

        item = WorkItem(type=WorkItemType.CHAT, input=WorkItemInput(prompt="hi"))
        assert item.agent_id == "default"

    def test_custom_agent_id(self) -> None:
        from autopoiesis.models import WorkItem, WorkItemInput, WorkItemType

        item = WorkItem(type=WorkItemType.CHAT, input=WorkItemInput(prompt="hi"), agent_id="prod")
        assert item.agent_id == "prod"
