"""Tests for shipped skills in the skills/ directory (Issue #163)."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopoiesis.skills.skills import (
    SkillDirectory,
    create_skills_toolset,
    discover_skills,
    parse_skill_md,
)

SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"


def _shipped_skill_dirs() -> list[Path]:
    if not SKILLS_ROOT.is_dir():
        return []
    return sorted(d for d in SKILLS_ROOT.iterdir() if d.is_dir() and (d / "SKILL.md").exists())


class TestShippedSkillDiscovery:
    def test_skills_directory_exists(self) -> None:
        assert SKILLS_ROOT.is_dir(), f"Shipped skills directory not found: {SKILLS_ROOT}"

    def test_at_least_one_shipped_skill(self) -> None:
        assert len(_shipped_skill_dirs()) > 0, "No shipped skills found"

    def test_discover_finds_all(self) -> None:
        dirs = [SkillDirectory(path=SKILLS_ROOT)]
        found = discover_skills(dirs)
        found_names = {s.name for s in found}
        for skill_dir in _shipped_skill_dirs():
            content = (skill_dir / "SKILL.md").read_text()
            fm, _ = parse_skill_md(content)
            name = fm.get("name")
            if isinstance(name, str) and name.strip():
                assert name in found_names, f"Skill '{name}' in {skill_dir} not discovered"


@pytest.mark.parametrize(
    "skill_dir",
    _shipped_skill_dirs(),
    ids=[d.name for d in _shipped_skill_dirs()],
)
class TestSkillStructure:
    def test_skill_md_exists_and_nonempty(self, skill_dir: Path) -> None:
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.exists()
        assert len(skill_md.read_text().strip()) > 0

    def test_skill_md_parses(self, skill_dir: Path) -> None:
        content = (skill_dir / "SKILL.md").read_text()
        fm, instructions = parse_skill_md(content)
        assert isinstance(fm, dict)
        assert isinstance(instructions, str)
        assert "name" in fm
        assert "description" in fm

    def test_no_dead_internal_refs(self, skill_dir: Path) -> None:
        for f in skill_dir.iterdir():
            if f.is_file():
                assert f.exists(), f"Dead reference: {f}"

    def test_loader_parses_without_error(self, skill_dir: Path) -> None:
        dirs = [SkillDirectory(path=skill_dir.parent)]
        found = discover_skills(dirs)
        content = (skill_dir / "SKILL.md").read_text()
        fm, _ = parse_skill_md(content)
        name = fm.get("name", "")
        matching = [s for s in found if s.name == name]
        assert len(matching) == 1


class TestSkillToolsetRegistration:
    def test_create_toolset_succeeds(self) -> None:
        dirs = [SkillDirectory(path=SKILLS_ROOT)]
        toolset, instructions = create_skills_toolset(dirs)
        assert toolset is not None
        assert isinstance(instructions, str)

    def test_toolset_instructions_mention_skills(self) -> None:
        dirs = [SkillDirectory(path=SKILLS_ROOT)]
        _, instructions = create_skills_toolset(dirs)
        for skill_dir in _shipped_skill_dirs():
            content = (skill_dir / "SKILL.md").read_text()
            fm, _ = parse_skill_md(content)
            name = fm.get("name", "")
            if name:
                assert name in instructions
