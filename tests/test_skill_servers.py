"""Tests for filesystem skill provider and skill server registration.

Phase 2: FastMCP skill servers auto-discovered from skills/ directory.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from autopoiesis.skills.filesystem_skill_provider import (
    discover_skill_providers,
    register_skill_providers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_server(skill_dir: Path, skill_name: str) -> None:
    """Write a minimal server.py with one @tool into *skill_dir*."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    code = f"""\
from fastmcp.tools import tool

@tool(tags={{"{skill_name}"}})
def greet(name: str) -> str:
    \"\"\"Greet someone.

    Args:
        name: The person's name.
    \"\"\"
    return f"Hello from {skill_name}, {{name}}!"
"""
    (skill_dir / "server.py").write_text(code)


# ---------------------------------------------------------------------------
# discover_skill_providers
# ---------------------------------------------------------------------------


class TestDiscoverSkillProviders:
    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        result = discover_skill_providers(tmp_path)
        assert result == []

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        result = discover_skill_providers(missing)
        assert result == []

    def test_skill_without_server_py_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "bare_skill").mkdir()
        (tmp_path / "bare_skill" / "SKILL.md").write_text("---\nname: bare\n---\nbody")
        result = discover_skill_providers(tmp_path)
        assert result == []

    def test_discovers_skill_with_server_py(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my_skill"
        _write_minimal_server(skill_dir, "my_skill")

        result = discover_skill_providers(tmp_path)
        names = [name for name, _ in result]
        assert "my_skill" in names

    def test_returns_file_system_provider(self, tmp_path: Path) -> None:
        from fastmcp.server.providers.filesystem import FileSystemProvider

        skill_dir = tmp_path / "alpha"
        _write_minimal_server(skill_dir, "alpha")

        result = discover_skill_providers(tmp_path)
        assert len(result) == 1
        _name, provider = result[0]
        assert isinstance(provider, FileSystemProvider)

    def test_discovers_multiple_skills(self, tmp_path: Path) -> None:
        for skill in ("alpha", "beta", "gamma"):
            _write_minimal_server(tmp_path / skill, skill)

        result = discover_skill_providers(tmp_path)
        names = sorted(name for name, _ in result)
        assert names == ["alpha", "beta", "gamma"]

    def test_sorted_by_skill_name(self, tmp_path: Path) -> None:
        for skill in ("zzz", "aaa", "mmm"):
            _write_minimal_server(tmp_path / skill, skill)

        result = discover_skill_providers(tmp_path)
        names = [name for name, _ in result]
        assert names == sorted(names)

    def test_non_directory_entries_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "not_a_dir.txt").write_text("ignored")
        skill_dir = tmp_path / "real_skill"
        _write_minimal_server(skill_dir, "real_skill")

        result = discover_skill_providers(tmp_path)
        names = [name for name, _ in result]
        assert "real_skill" in names
        assert len(names) == 1


# ---------------------------------------------------------------------------
# register_skill_providers
# ---------------------------------------------------------------------------


class TestRegisterSkillProviders:
    def _make_mock_server(self) -> object:
        """Return a simple mock that records add_provider calls."""
        calls: list[tuple[object, str]] = []

        class _MockServer:
            registered: list[tuple[object, str]] = calls

            def add_provider(self, provider: object, *, namespace: str = "") -> None:
                calls.append((provider, namespace))

        return _MockServer()

    def test_registers_nothing_for_empty_dir(self, tmp_path: Path) -> None:
        server = self._make_mock_server()
        registered = register_skill_providers(server, tmp_path)
        assert registered == []

    def test_registers_skill_and_returns_name(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "demo"
        _write_minimal_server(skill_dir, "demo")

        server = self._make_mock_server()
        registered = register_skill_providers(server, tmp_path)
        assert "demo" in registered

    def test_namespace_matches_skill_name(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "ns_test"
        _write_minimal_server(skill_dir, "ns_test")

        server = self._make_mock_server()
        register_skill_providers(server, tmp_path)

        assert any(ns == "ns_test" for _, ns in server.registered)  # type: ignore[attr-defined]

    def test_multiple_skills_all_registered(self, tmp_path: Path) -> None:
        for skill in ("one", "two"):
            _write_minimal_server(tmp_path / skill, skill)

        server = self._make_mock_server()
        registered = register_skill_providers(server, tmp_path)
        assert set(registered) == {"one", "two"}


# ---------------------------------------------------------------------------
# Integration: tools are visible/namespaced on FastMCP server
# ---------------------------------------------------------------------------


class TestSkillServerIntegration:
    def test_tools_namespaced_on_mcp_server(self, tmp_path: Path) -> None:
        """Skill tools appear as {namespace}_{tool_name} on the FastMCP server."""
        from fastmcp import FastMCP

        skill_dir = tmp_path / "myskill"
        _write_minimal_server(skill_dir, "myskill")

        server = FastMCP("test")
        register_skill_providers(server, tmp_path)

        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        assert "myskill_greet" in names

    def test_tags_preserved_after_registration(self, tmp_path: Path) -> None:
        """Tool tags survive FileSystemProvider → add_provider pipeline."""
        from fastmcp import FastMCP

        skill_dir = tmp_path / "tagged_skill"
        _write_minimal_server(skill_dir, "tagged_skill")

        server = FastMCP("test")
        register_skill_providers(server, tmp_path)

        tools = asyncio.run(server.list_tools())
        greet_tool = next((t for t in tools if t.name == "tagged_skill_greet"), None)
        assert greet_tool is not None
        assert "tagged_skill" in greet_tool.tags  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Shipped skillmaker skill
# ---------------------------------------------------------------------------


class TestShippedSkillmakerServer:
    """Validate that the shipped skills/skillmaker/server.py is well-formed."""

    @pytest.fixture()
    def skills_root(self) -> Path:
        return Path(__file__).resolve().parent.parent / "skills"

    def test_server_py_exists(self, skills_root: Path) -> None:
        server_py = skills_root / "skillmaker" / "server.py"
        assert server_py.exists(), f"Missing: {server_py}"

    def test_skillmaker_discovered(self, skills_root: Path) -> None:
        result = discover_skill_providers(skills_root)
        names = [name for name, _ in result]
        assert "skillmaker" in names

    def test_skillmaker_tools_on_server(self, skills_root: Path) -> None:
        from fastmcp import FastMCP

        server = FastMCP("test")
        register_skill_providers(server, skills_root)

        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        assert "skillmaker_validate" in names
        assert "skillmaker_lint" in names

    def test_skillmaker_validate_works(self, skills_root: Path) -> None:
        from fastmcp import FastMCP

        server = FastMCP("test")
        register_skill_providers(server, skills_root)

        result = asyncio.run(
            server.call_tool(
                "skillmaker_validate",
                {
                    "skill_name": "test",
                    "frontmatter_yaml": (
                        "name: test\ndescription: A test.\n"
                        "metadata:\n  version: '1.0.0'\n  tags: [test]\n"
                    ),
                    "instructions": "# Test\n\nSome instructions.",
                },
            )
        )
        assert result is not None
        output = str(result)
        assert "PASSED" in output or "validation" in output.lower()

    def test_skillmaker_tags_present(self, skills_root: Path) -> None:
        from fastmcp import FastMCP

        server = FastMCP("test")
        register_skill_providers(server, skills_root)

        tools = asyncio.run(server.list_tools())
        for t in tools:
            if t.name.startswith("skillmaker_"):  # type: ignore[union-attr]
                tags: set[str] = getattr(t, "tags", set())  # type: ignore[assignment]
                assert "skillmaker" in tags, f"Tool {t.name} missing 'skillmaker' tag"  # type: ignore[union-attr]
