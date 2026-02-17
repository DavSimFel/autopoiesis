"""Section 9: Skill Loading integration tests."""

from __future__ import annotations

from pathlib import Path

from autopoiesis.skills.skills import (
    SkillDirectory,
    discover_skills,
    load_skill_instructions,
)


def _create_skill(skills_dir: Path, name: str, content: str) -> Path:
    """Create a skill directory with SKILL.md."""
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


_VALID_SKILL = """\
---
name: test-skill
description: A test skill for integration tests
tags: [testing, integration]
version: "1.0.0"
---

# Test Skill Instructions

Use this skill to run tests.
"""

_CUSTOM_WEB_SKILL = """\
---
name: web
description: Custom web skill override
tags: [web]
version: "2.0.0"
---

# Custom Web

This overrides the shipped web skill.
"""

_SHIPPED_WEB_SKILL = """\
---
name: web
description: Shipped web skill
tags: [web]
version: "1.0.0"
---

# Shipped Web

Default web skill.
"""

_BROKEN_SKILL = """\
---
- this is not a mapping
---

Some instructions.
"""


class TestSkillDiscovery:
    """9.1 — Skill discovered from directory."""

    def test_discover_from_directory(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "my-skill", _VALID_SKILL)
        # Also create a tools.py to verify resources are found
        (skills_dir / "my-skill" / "tools.py").write_text("def run(): pass\n")

        discovered = discover_skills([SkillDirectory(path=skills_dir)])
        assert len(discovered) == 1
        assert discovered[0].name == "test-skill"
        assert "tools.py" in discovered[0].resources

    def test_load_instructions(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "my-skill", _VALID_SKILL)
        discovered = discover_skills([SkillDirectory(path=skills_dir)])
        cache = {s.name: s for s in discovered}

        instructions = load_skill_instructions(cache, "test-skill")
        assert "Test Skill Instructions" in instructions
        assert "run tests" in instructions


class TestCustomSkillOverridesShipped:
    """9.2 — Custom skill overrides shipped."""

    def test_custom_takes_precedence(self, tmp_path: Path) -> None:
        shipped_dir = tmp_path / "shipped"
        custom_dir = tmp_path / "custom"
        _create_skill(shipped_dir, "web", _SHIPPED_WEB_SKILL)
        _create_skill(custom_dir, "web", _CUSTOM_WEB_SKILL)

        # Custom directory listed AFTER shipped — last wins in dict
        discovered = discover_skills(
            [
                SkillDirectory(path=shipped_dir),
                SkillDirectory(path=custom_dir),
            ]
        )
        cache = {s.name: s for s in discovered}
        assert "web" in cache
        # The last-discovered (custom) should be in the cache
        assert cache["web"].description == "Custom web skill override"


class TestInvalidSkillIgnored:
    """9.3 — Invalid skill ignored gracefully."""

    def test_broken_skill_skipped(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "good-skill", _VALID_SKILL)
        _create_skill(skills_dir, "broken-skill", _BROKEN_SKILL)

        discovered = discover_skills([SkillDirectory(path=skills_dir)])
        names = [s.name for s in discovered]
        assert "test-skill" in names
        assert len(discovered) == 1  # broken one not included
