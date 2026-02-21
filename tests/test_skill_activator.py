"""Tests for SkillActivator — lazy loading and topic activation wiring.

Phase 2: skill_activator.py enables/disables FastMCP tools when skills
are activated via topics.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock


class TestSkillActivatorBasics:
    """Unit tests for SkillActivator with a mock MCP server."""

    def _make_activator(self, tmp_path: Path, skill_names: list[str]) -> object:
        """Create a SkillActivator with fake skill directories."""
        from autopoiesis.skills.skill_activator import SkillActivator

        for name in skill_names:
            skill_dir = tmp_path / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "server.py").write_text(f"# {name} server")

        mock_mcp = MagicMock()
        return SkillActivator(mock_mcp, tmp_path)

    def test_initial_state_all_inactive(self, tmp_path: Path) -> None:
        activator = self._make_activator(tmp_path, ["skill_a", "skill_b"])
        assert activator.active_skills == frozenset()  # type: ignore[attr-defined]

    def test_activate_existing_skill(self, tmp_path: Path) -> None:
        activator = self._make_activator(tmp_path, ["skill_a"])
        result = activator.activate("skill_a")  # type: ignore[attr-defined]
        assert result is True

    def test_activate_calls_enable_on_mcp(self, tmp_path: Path) -> None:
        from autopoiesis.skills.skill_activator import SkillActivator

        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "server.py").write_text("# server")

        mock_mcp = MagicMock()
        activator = SkillActivator(mock_mcp, tmp_path)
        activator.activate("my_skill")

        mock_mcp.enable.assert_called_once_with(tags={"my_skill"})

    def test_activate_missing_skill_returns_false(self, tmp_path: Path) -> None:
        activator = self._make_activator(tmp_path, [])
        result = activator.activate("nonexistent")  # type: ignore[attr-defined]
        assert result is False

    def test_activate_missing_skill_does_not_call_enable(self, tmp_path: Path) -> None:
        from autopoiesis.skills.skill_activator import SkillActivator

        mock_mcp = MagicMock()
        activator = SkillActivator(mock_mcp, tmp_path)
        activator.activate("no_server_py_skill")

        mock_mcp.enable.assert_not_called()

    def test_skill_without_server_py_returns_false(self, tmp_path: Path) -> None:
        from autopoiesis.skills.skill_activator import SkillActivator

        skill_dir = tmp_path / "bare_skill"
        skill_dir.mkdir()
        # No server.py

        mock_mcp = MagicMock()
        activator = SkillActivator(mock_mcp, tmp_path)
        result = activator.activate("bare_skill")

        assert result is False

    def test_is_active_after_activate(self, tmp_path: Path) -> None:
        activator = self._make_activator(tmp_path, ["alpha"])
        activator.activate("alpha")  # type: ignore[attr-defined]
        assert activator.is_active("alpha") is True  # type: ignore[attr-defined]

    def test_is_active_false_before_activate(self, tmp_path: Path) -> None:
        activator = self._make_activator(tmp_path, ["alpha"])
        assert activator.is_active("alpha") is False  # type: ignore[attr-defined]

    def test_active_skills_updated_on_activate(self, tmp_path: Path) -> None:
        activator = self._make_activator(tmp_path, ["alpha", "beta"])
        activator.activate("alpha")  # type: ignore[attr-defined]
        assert "alpha" in activator.active_skills  # type: ignore[attr-defined]
        assert "beta" not in activator.active_skills  # type: ignore[attr-defined]


class TestSkillActivatorDeactivation:
    def _make_activator(self, tmp_path: Path, skill_names: list[str]) -> object:
        from autopoiesis.skills.skill_activator import SkillActivator

        for name in skill_names:
            skill_dir = tmp_path / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "server.py").write_text(f"# {name} server")

        mock_mcp = MagicMock()
        return SkillActivator(mock_mcp, tmp_path)

    def test_deactivate_active_skill(self, tmp_path: Path) -> None:
        activator = self._make_activator(tmp_path, ["skill_a"])
        activator.activate("skill_a")  # type: ignore[attr-defined]
        result = activator.deactivate("skill_a")  # type: ignore[attr-defined]
        assert result is True

    def test_deactivate_calls_disable_on_mcp(self, tmp_path: Path) -> None:
        from autopoiesis.skills.skill_activator import SkillActivator

        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "server.py").write_text("# server")

        mock_mcp = MagicMock()
        activator = SkillActivator(mock_mcp, tmp_path)
        activator.activate("my_skill")
        activator.deactivate("my_skill")

        mock_mcp.disable.assert_called_once_with(tags={"my_skill"})

    def test_deactivate_inactive_skill_returns_false(self, tmp_path: Path) -> None:
        activator = self._make_activator(tmp_path, ["skill_a"])
        result = activator.deactivate("skill_a")  # type: ignore[attr-defined]
        assert result is False

    def test_is_active_false_after_deactivate(self, tmp_path: Path) -> None:
        activator = self._make_activator(tmp_path, ["alpha"])
        activator.activate("alpha")  # type: ignore[attr-defined]
        activator.deactivate("alpha")  # type: ignore[attr-defined]
        assert activator.is_active("alpha") is False  # type: ignore[attr-defined]

    def test_active_skills_cleared_after_deactivate(self, tmp_path: Path) -> None:
        activator = self._make_activator(tmp_path, ["alpha"])
        activator.activate("alpha")  # type: ignore[attr-defined]
        activator.deactivate("alpha")  # type: ignore[attr-defined]
        assert "alpha" not in activator.active_skills  # type: ignore[attr-defined]


class TestSkillActivatorTopicWiring:
    def _make_activator(self, tmp_path: Path, skill_names: list[str]) -> object:
        from autopoiesis.skills.skill_activator import SkillActivator

        for name in skill_names:
            skill_dir = tmp_path / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "server.py").write_text(f"# {name} server")

        mock_mcp = MagicMock()
        return SkillActivator(mock_mcp, tmp_path)

    def test_activate_skill_for_topic_uses_topic_name_by_default(
        self, tmp_path: Path
    ) -> None:
        activator = self._make_activator(tmp_path, ["github"])
        result = activator.activate_skill_for_topic("github")  # type: ignore[attr-defined]
        assert result is True
        assert activator.is_active("github") is True  # type: ignore[attr-defined]

    def test_activate_skill_for_topic_uses_explicit_skill_name(
        self, tmp_path: Path
    ) -> None:
        activator = self._make_activator(tmp_path, ["custom_skill"])
        result = activator.activate_skill_for_topic(  # type: ignore[attr-defined]
            "my_topic", skill_name="custom_skill"
        )
        assert result is True

    def test_activate_skill_for_topic_missing_returns_false(
        self, tmp_path: Path
    ) -> None:
        activator = self._make_activator(tmp_path, [])
        result = activator.activate_skill_for_topic("no_matching_skill")  # type: ignore[attr-defined]
        assert result is False


class TestSkillActivatorIntegration:
    """End-to-end test with a real FastMCP server."""

    def _write_skill_server(self, skill_dir: Path, skill_name: str) -> None:
        skill_dir.mkdir(parents=True, exist_ok=True)
        code = f"""\
from fastmcp.tools import tool

@tool(tags={{"{skill_name}"}})
def work(task: str) -> str:
    \"\"\"Do work.

    Args:
        task: The task description.
    \"\"\"
    return f"Done: {{task}}"
"""
        (skill_dir / "server.py").write_text(code)

    def test_tools_hidden_at_startup(self, tmp_path: Path) -> None:
        """Tools registered with disable transform are hidden by default."""
        from fastmcp import FastMCP

        from autopoiesis.skills.filesystem_skill_provider import register_skill_providers
        from autopoiesis.skills.skill_transforms import make_skill_disable_transform

        self._write_skill_server(tmp_path / "lazy_skill", "lazy_skill")

        mcp = FastMCP("test")
        register_skill_providers(mcp, tmp_path)
        for t in make_skill_disable_transform("lazy_skill"):
            mcp.add_transform(t)

        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        assert "lazy_skill_work" not in names

    def test_tools_visible_after_activate(self, tmp_path: Path) -> None:
        """SkillActivator.activate() makes tools visible."""
        from fastmcp import FastMCP

        from autopoiesis.skills.filesystem_skill_provider import register_skill_providers
        from autopoiesis.skills.skill_activator import SkillActivator
        from autopoiesis.skills.skill_transforms import make_skill_disable_transform

        self._write_skill_server(tmp_path / "lazy_skill", "lazy_skill")

        mcp = FastMCP("test")
        register_skill_providers(mcp, tmp_path)
        for t in make_skill_disable_transform("lazy_skill"):
            mcp.add_transform(t)

        activator = SkillActivator(mcp, tmp_path)
        activator.activate("lazy_skill")

        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        assert "lazy_skill_work" in names

    def test_tools_hidden_again_after_deactivate(self, tmp_path: Path) -> None:
        """Tools disappear after deactivation."""
        from fastmcp import FastMCP

        from autopoiesis.skills.filesystem_skill_provider import register_skill_providers
        from autopoiesis.skills.skill_activator import SkillActivator
        from autopoiesis.skills.skill_transforms import make_skill_disable_transform

        self._write_skill_server(tmp_path / "lazy_skill", "lazy_skill")

        mcp = FastMCP("test")
        register_skill_providers(mcp, tmp_path)
        for t in make_skill_disable_transform("lazy_skill"):
            mcp.add_transform(t)

        activator = SkillActivator(mcp, tmp_path)
        activator.activate("lazy_skill")
        assert "lazy_skill_work" in {t.name for t in asyncio.run(mcp.list_tools())}

        activator.deactivate("lazy_skill")
        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        assert "lazy_skill_work" not in names
