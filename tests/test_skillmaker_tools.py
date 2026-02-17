"""Tests for skill metadata linting and validation helpers."""

from typing import Any

from autopoiesis.skills.skillmaker_tools import validate_skill_definition


def test_validate_requires_metadata_version_and_tags() -> None:
    metadata: dict[str, Any] = {"author": "dev"}
    frontmatter: dict[str, Any] = {
        "name": "demo-skill",
        "description": "Demo",
        "metadata": metadata,
    }
    instructions = "# Demo Skill\n\nDetails."

    result = validate_skill_definition("demo-skill", frontmatter, instructions)

    assert "FAILED" in result
    assert "metadata" in result


def test_validate_requires_non_empty_tags() -> None:
    tags: list[str] = []
    metadata: dict[str, Any] = {"version": "1.0.0", "tags": tags}
    frontmatter: dict[str, Any] = {
        "name": "demo-skill",
        "description": "Demo",
        "metadata": metadata,
    }
    instructions = "# Demo Skill\n\nDetails."

    result = validate_skill_definition("demo-skill", frontmatter, instructions)

    assert "FAILED" in result
    assert "include at least one tag" in result


def test_validate_passes_with_required_metadata() -> None:
    metadata: dict[str, Any] = {"version": "1.0.0", "tags": ["demo"]}
    frontmatter: dict[str, Any] = {
        "name": "demo-skill",
        "description": "Demo",
        "metadata": metadata,
    }
    instructions = "# Demo Skill\n\nDetails."

    result = validate_skill_definition("demo-skill", frontmatter, instructions)

    assert result == "Skill validation PASSED: demo-skill"
