"""Tests for skills: discover_skills, parse_skill_md, and edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopoiesis.skills.skills import Skill, SkillDirectory, discover_skills, parse_skill_md


def _write_skill(directory: Path, name: str, description: str = "A test skill") -> Path:
    """Write a valid SKILL.md into a subdirectory and return the skill dir."""
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = (
        f"---\nname: {name}\ndescription: {description}\n"
        f"metadata:\n  version: '1.0.0'\n  tags: [test]\n"
        f"---\nInstructions for {name}."
    )
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


class TestParseSkillMd:
    """Tests for parse_skill_md with various inputs."""

    def test_valid_frontmatter(self) -> None:
        content = "---\nname: demo\ndescription: A demo\n---\nHello world."
        fm, instructions = parse_skill_md(content)
        assert fm["name"] == "demo"
        assert fm["description"] == "A demo"
        assert instructions == "Hello world."

    def test_missing_frontmatter(self) -> None:
        content = "Just plain instructions."
        fm, instructions = parse_skill_md(content)
        assert fm == {}
        assert instructions == "Just plain instructions."

    def test_invalid_yaml_raises(self) -> None:
        content = "---\n: [invalid yaml\n---\nbody"
        import yaml

        with pytest.raises(yaml.YAMLError):
            parse_skill_md(content)

    def test_non_mapping_frontmatter_raises(self) -> None:
        content = "---\n- list item\n---\nbody"
        with pytest.raises(ValueError, match="must be a mapping"):
            parse_skill_md(content)

    def test_empty_frontmatter(self) -> None:
        content = "---\n---\nJust instructions."
        fm, instructions = parse_skill_md(content)
        assert fm == {}
        assert instructions == "Just instructions."

    def test_no_closing_delimiter(self) -> None:
        content = "---\nname: broken\nno closing"
        fm, instructions = parse_skill_md(content)
        assert fm == {}
        assert "no closing" in instructions

    def test_multiline_instructions(self) -> None:
        content = "---\nname: multi\n---\nLine 1\nLine 2\nLine 3"
        _, instructions = parse_skill_md(content)
        assert "Line 1" in instructions
        assert "Line 3" in instructions


class TestDiscoverSkills:
    """Tests for discover_skills with mock skill directories."""

    def test_discovers_valid_skills(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "alpha")
        _write_skill(tmp_path, "beta")
        dirs = [SkillDirectory(path=tmp_path)]
        skills = discover_skills(dirs)
        names = {s.name for s in skills}
        assert "alpha" in names
        assert "beta" in names

    def test_skips_missing_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        skills = discover_skills([SkillDirectory(path=missing)])
        assert skills == []

    def test_skips_skill_without_name(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "noname"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ndescription: no name\n---\nbody")
        skills = discover_skills([SkillDirectory(path=tmp_path)])
        assert all(s.name != "" for s in skills)

    def test_skips_invalid_yaml(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "broken"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\n: [bad\n---\nbody")
        skills = discover_skills([SkillDirectory(path=tmp_path)])
        assert len(skills) == 0

    def test_multiple_directories(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        _write_skill(dir_a, "skill_a")
        _write_skill(dir_b, "skill_b")
        dirs = [SkillDirectory(path=dir_a), SkillDirectory(path=dir_b)]
        skills = discover_skills(dirs)
        names = {s.name for s in skills}
        assert names == {"skill_a", "skill_b"}

    def test_non_recursive_mode(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "top_level")
        nested = tmp_path / "top_level" / "nested"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text(
            "---\nname: deep\ndescription: deep\n"
            "metadata:\n  version: '1.0.0'\n  tags: []\n"
            "---\ndeep instructions"
        )
        dirs = [SkillDirectory(path=tmp_path, recursive=False)]
        skills = discover_skills(dirs)
        names = {s.name for s in skills}
        assert "top_level" in names

    def test_collects_resources(self, tmp_path: Path) -> None:
        skill_dir = _write_skill(tmp_path, "with_res")
        (skill_dir / "helper.py").write_text("# helper")
        (skill_dir / "data.json").write_text("{}")
        dirs = [SkillDirectory(path=tmp_path)]
        skills = discover_skills(dirs)
        target = next(s for s in skills if s.name == "with_res")
        assert "helper.py" in target.resources
        assert "data.json" in target.resources


class TestLoadSkillInstructions:
    """Tests for loading instructions with missing SKILL.md."""

    def test_missing_skill_file(self, tmp_path: Path) -> None:
        from autopoiesis.skills.skills import load_skill_instructions

        skill = Skill(name="ghost", description="gone", path=tmp_path / "ghost")
        cache = {"ghost": skill}
        result = load_skill_instructions(cache, "ghost")
        assert "not found" in result.lower() or "SKILL.md" in result
