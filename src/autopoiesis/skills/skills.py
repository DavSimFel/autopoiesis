"""Filesystem-based skill system with progressive disclosure."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from autopoiesis.models import AgentDeps
from autopoiesis.security.path_validator import PathValidator
from autopoiesis.skills.skillmaker_tools import (
    extract_skill_metadata,
    lint_skill_definition,
    validate_skill_definition,
)

logger = logging.getLogger(__name__)


class SkillDirectory(BaseModel):
    """A directory to scan for skills."""

    path: Path
    recursive: bool = True


class Skill(BaseModel):
    """Skill metadata with lazy-loaded instructions."""

    name: str
    description: str
    path: Path
    tags: list[str] = []
    version: str = "1.0.0"
    author: str = ""
    resources: list[str] = []
    instructions: str | None = None
    instructions_mtime: float | None = None


def parse_skill_md(content: str) -> tuple[dict[str, Any], str]:
    """Parse a SKILL.md file into (frontmatter dict, instructions string)."""
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, content.strip()

    closing_idx: int | None = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_idx = idx
            break
    if closing_idx is None:
        return {}, content.strip()

    frontmatter_yaml = "".join(lines[1:closing_idx]).strip()
    instructions = "".join(lines[closing_idx + 1 :]).strip()

    loaded_frontmatter: object = yaml.safe_load(frontmatter_yaml) if frontmatter_yaml else {}
    if not isinstance(loaded_frontmatter, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping.")
    frontmatter = cast(dict[str, Any], loaded_frontmatter)
    return frontmatter, instructions


def discover_skills(directories: list[SkillDirectory]) -> list[Skill]:
    """Discover skills from directories, returning metadata (no instructions)."""
    skills: list[Skill] = []

    for skill_dir in directories:
        dir_path = skill_dir.path.expanduser()
        if not dir_path.exists():
            logger.debug("Skills directory %s does not exist, skipping", dir_path)
            continue

        pattern = "**/SKILL.md" if skill_dir.recursive else "*/SKILL.md"
        for skill_file in dir_path.glob(pattern):
            try:
                content = skill_file.read_text()
                frontmatter, _ = parse_skill_md(content)
                name_raw = frontmatter.get("name")
                if not isinstance(name_raw, str) or not name_raw.strip():
                    continue
                description, tags, version, author = extract_skill_metadata(frontmatter)

                skill_folder = skill_file.parent
                resources = [
                    str(f.relative_to(skill_folder))
                    for f in skill_folder.iterdir()
                    if f.is_file() and f.name != "SKILL.md"
                ]

                skills.append(
                    Skill(
                        name=name_raw,
                        description=description,
                        path=skill_folder,
                        tags=tags,
                        version=version,
                        author=author,
                        resources=resources,
                    )
                )
            except (
                OSError,
                UnicodeDecodeError,
                ValueError,
                TypeError,
                yaml.YAMLError,
                ValidationError,
            ):
                logger.warning("Failed to parse skill at %s", skill_file, exc_info=True)
                continue

    return skills


def _format_skill_list(cache: dict[str, Skill]) -> str:
    """Format the skill cache into a human-readable list."""
    if not cache:
        return "No skills available."
    lines = ["Available Skills:", ""]
    for name, skill in sorted(cache.items()):
        tags = ", ".join(skill.tags) if skill.tags else "none"
        lines.append(f"- **{name}** (v{skill.version}): {skill.description} [{tags}]")
    return "\n".join(lines)


def load_skill_instructions(cache: dict[str, Skill], skill_name: str) -> str:
    """Load full instructions for a skill, with mtime-based cache invalidation."""
    if skill_name not in cache:
        available = ", ".join(sorted(cache.keys())) if cache else "none"
        return f"Skill '{skill_name}' not found. Available: {available}"

    skill = cache[skill_name]
    skill_file = skill.path / "SKILL.md"

    # Check if cached instructions are stale via file mtime.
    if skill.instructions is not None and skill.instructions_mtime is not None:
        try:
            current_mtime = skill_file.stat().st_mtime
        except OSError:
            current_mtime = None
        if current_mtime is not None and current_mtime != skill.instructions_mtime:
            skill.instructions = None
            skill.instructions_mtime = None

    if skill.instructions is None:
        if not skill_file.exists():
            return f"SKILL.md not found at {skill.path}"
        content = skill_file.read_text()
        _, skill.instructions = parse_skill_md(content)
        try:
            skill.instructions_mtime = skill_file.stat().st_mtime
        except OSError:
            skill.instructions_mtime = None

    return f"# Skill: {skill.name}\n\n{skill.instructions}"


def _read_resource(cache: dict[str, Skill], skill_name: str, resource_name: str) -> str:
    """Read a resource file with path-traversal protection."""
    skill = cache.get(skill_name)
    if skill is None:
        return f"Skill '{skill_name}' not found."
    avail = ", ".join(sorted(skill.resources)) if skill.resources else "none"
    error = _validate_resource_path(skill, resource_name, avail)
    if error is not None:
        return error
    validator = PathValidator(workspace_root=skill.path)
    resolved = validator.resolve_path(resource_name)
    try:
        return resolved.read_text()
    except (OSError, UnicodeDecodeError):
        logger.warning("Failed to read resource %s for skill %s", resource_name, skill_name)
        return f"Error reading resource '{resource_name}'."


def _validate_resource_path(skill: Skill, resource_name: str, avail: str) -> str | None:
    """Return an error message if the resource path is invalid, else None."""
    if resource_name not in skill.resources:
        return f"Resource '{resource_name}' not listed. Available: {avail}"
    validator = PathValidator(workspace_root=skill.path)
    try:
        resolved = validator.resolve_path(resource_name)
    except ValueError:
        return "Error: resource path escapes skill directory."
    if not resolved.exists():
        return f"Resource '{resource_name}' not found. Available: {avail}"
    if not resolved.is_file():
        return f"Resource '{resource_name}' is not a file."
    return None


def _validate_skill(cache: dict[str, Skill], skill_name: str) -> str:
    skill = cache.get(skill_name)
    if skill is None:
        return f"Skill '{skill_name}' not found."
    try:
        content = (skill.path / "SKILL.md").read_text()
        frontmatter, instructions = parse_skill_md(content)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        logger.warning("Failed to validate skill %s", skill_name, exc_info=True)
        return f"Error validating skill '{skill_name}'."
    return validate_skill_definition(skill_name, frontmatter, instructions)


def _lint_skill(cache: dict[str, Skill], skill_name: str) -> str:
    skill = cache.get(skill_name)
    if skill is None:
        return f"Skill '{skill_name}' not found."
    try:
        content = (skill.path / "SKILL.md").read_text()
        _, instructions = parse_skill_md(content)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        logger.warning("Failed to lint skill %s", skill_name, exc_info=True)
        return f"Error linting skill '{skill_name}'."
    return lint_skill_definition(skill_name, instructions)


def skills_instructions(cache: dict[str, Skill]) -> str:
    """Generate a system prompt fragment listing available skills."""
    if not cache:
        return ""
    names = ", ".join(sorted(cache.keys()))
    return (
        f"## Skills\nAvailable skills: {names}.\n"
        "Use `list_skills` to browse, `load_skill` before using one."
    )


def create_skills_toolset(
    directories: list[SkillDirectory],
) -> tuple[FunctionToolset[AgentDeps], str]:
    """Create skills tools and return (toolset, system prompt fragment)."""
    toolset: FunctionToolset[AgentDeps] = FunctionToolset(
        docstring_format="google",
        require_parameter_descriptions=True,
    )
    skill_meta: dict[str, str] = {"category": "skills"}

    discovered = discover_skills(directories)
    cache: dict[str, Skill] = {s.name: s for s in discovered}

    @toolset.tool(metadata=skill_meta)
    async def list_skills(ctx: RunContext[AgentDeps]) -> str:
        """Show available skills with names, descriptions, and tags."""
        return _format_skill_list(cache)

    @toolset.tool(metadata=skill_meta)
    async def load_skill(ctx: RunContext[AgentDeps], skill_name: str) -> str:
        """Load full instructions for a skill.

        Args:
            skill_name: Skill name as shown by list_skills.
        """
        return load_skill_instructions(cache, skill_name)

    @toolset.tool(metadata=skill_meta)
    async def read_skill_resource(
        ctx: RunContext[AgentDeps],
        skill_name: str,
        resource_name: str,
    ) -> str:
        """Read a supporting file from a skill directory.

        Args:
            skill_name: Skill that owns the resource.
            resource_name: Filename within the skill directory.
        """
        return _read_resource(cache, skill_name, resource_name)

    @toolset.tool(metadata=skill_meta)
    async def validate_skill(ctx: RunContext[AgentDeps], skill_name: str) -> str:
        """Check a skill's SKILL.md for structural correctness.

        Args:
            skill_name: Skill to validate.
        """
        return _validate_skill(cache, skill_name)

    @toolset.tool(metadata=skill_meta)
    async def lint_skill(ctx: RunContext[AgentDeps], skill_name: str) -> str:
        """Lint a skill's instructions for style issues.

        Args:
            skill_name: Skill to lint.
        """
        return _lint_skill(cache, skill_name)

    # Ensure pyright recognizes decorator-registered functions as used
    _ = (list_skills, load_skill, read_skill_resource, validate_skill, lint_skill)

    return toolset, skills_instructions(cache)
