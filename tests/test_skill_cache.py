"""Tests for skill instruction cache invalidation on file mtime change."""

from pathlib import Path

from autopoiesis.skills.skills import Skill, load_skill_instructions


def _make_skill_dir(tmp_path: Path, name: str, instructions: str) -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    frontmatter = (
        f"---\nname: {name}\ndescription: test\n"
        f"metadata:\n  version: '1.0.0'\n  tags: [test]\n"
        f"---\n{instructions}"
    )
    skill_file.write_text(frontmatter)
    return skill_dir


def test_load_skill_caches_instructions(tmp_path: Path) -> None:
    """First load caches instructions; second load returns cached value."""
    skill_dir = _make_skill_dir(tmp_path, "demo", "original instructions")
    skill = Skill(name="demo", description="test", path=skill_dir)
    cache = {"demo": skill}

    result1 = load_skill_instructions(cache, "demo")
    assert "original instructions" in result1
    assert skill.instructions is not None
    assert skill.instructions_mtime is not None

    # Second call returns cached (no re-read).
    result2 = load_skill_instructions(cache, "demo")
    assert result2 == result1


def test_load_skill_invalidates_on_mtime_change(tmp_path: Path) -> None:
    """Cache is invalidated when the SKILL.md file mtime changes."""
    import os
    import time

    skill_dir = _make_skill_dir(tmp_path, "demo", "original instructions")
    skill = Skill(name="demo", description="test", path=skill_dir)
    cache = {"demo": skill}

    load_skill_instructions(cache, "demo")
    assert "original instructions" in (skill.instructions or "")

    # Modify the file with a different mtime.
    skill_file = skill_dir / "SKILL.md"
    # Ensure mtime actually changes (some filesystems have 1s resolution).
    time.sleep(0.05)
    updated = (
        "---\nname: demo\ndescription: test\n"
        "metadata:\n  version: '1.0.0'\n  tags: [test]\n"
        "---\nupdated instructions"
    )
    skill_file.write_text(updated)
    # Force a different mtime if filesystem resolution is too coarse.
    current_mtime = skill.instructions_mtime or 0.0
    os.utime(skill_file, (current_mtime + 1, current_mtime + 1))

    result = load_skill_instructions(cache, "demo")
    assert "updated instructions" in result


def test_load_skill_not_found() -> None:
    """Loading a nonexistent skill returns a helpful message."""
    cache: dict[str, Skill] = {}
    result = load_skill_instructions(cache, "nope")
    assert "not found" in result.lower()
