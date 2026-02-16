"""Filesystem-based skill system with progressive disclosure.

Skills are folders containing a ``SKILL.md`` with YAML frontmatter (metadata)
and markdown body (instructions). The agent discovers skills at startup by
scanning frontmatter only — full instructions are loaded on demand to keep token usage low.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from models import AgentDeps
from skillmaker_tools import (
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
    """Parse a SKILL.md file into frontmatter and markdown instructions.

    Frontmatter is optional and delimited by ``---`` on its own line.
    If the delimiters are missing or malformed, returns an empty frontmatter
    mapping and treats the entire file as instruction content.
    """
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

    safe_load_obj = getattr(yaml, "safe_load", None)
    if not callable(safe_load_obj):
        raise ValueError("PyYAML safe_load is unavailable.")
    safe_load = cast(Callable[[str], object], safe_load_obj)
    loaded_frontmatter: object = safe_load(frontmatter_yaml) if frontmatter_yaml else {}
    if not isinstance(loaded_frontmatter, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping.")
    frontmatter = cast(dict[str, Any], loaded_frontmatter)
    return frontmatter, instructions


def discover_skills(directories: list[SkillDirectory]) -> list[Skill]:
    """Discover skills and build metadata cache from SKILL frontmatter.

    Discovery is resilient: parse errors in individual skill folders are logged
    and skipped so one bad skill file does not prevent startup.
    """
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
    """Load and return full instructions for a skill, caching for future calls.

    Instructions are cached after first load but invalidated when the
    SKILL.md file's mtime changes, so edits during a session are picked up.
    """
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
    """Read a resource file from a skill directory with path traversal protection."""
    skill = cache.get(skill_name)
    if skill is None:
        return f"Skill '{skill_name}' not found."

    error_message: str | None = None
    resolved_path: Path | None = None

    if resource_name not in skill.resources:
        error_message = (
            f"Resource '{resource_name}' is not listed for skill '{skill_name}'. "
            f"Available: {_format_available_resources(skill.resources)}"
        )
    else:
        resolved_path = (skill.path / resource_name).resolve()
        skill_dir_resolved = skill.path.resolve()
        if not resolved_path.is_relative_to(skill_dir_resolved):
            error_message = "Error: resource path escapes skill directory."
        elif not resolved_path.exists():
            error_message = (
                f"Resource '{resource_name}' not found. "
                f"Available: {_format_available_resources(skill.resources)}"
            )
        elif not resolved_path.is_file():
            error_message = f"Resource '{resource_name}' is not a file."

    if error_message is not None:
        return error_message

    if resolved_path is None:
        return f"Resource '{resource_name}' could not be resolved."
    try:
        return resolved_path.read_text()
    except (OSError, UnicodeDecodeError):
        logger.warning("Failed to read resource %s for skill %s", resource_name, skill_name)
        return f"Error reading resource '{resource_name}'."


def _format_available_resources(resources: list[str]) -> str:
    """Format a stable resource list for user-facing error messages."""
    if not resources:
        return "none"
    return ", ".join(sorted(resources))


def _load_skill_parts(skill: Skill) -> tuple[dict[str, Any], str]:
    """Read and parse SKILL.md for lint/validation checks."""
    content = (skill.path / "SKILL.md").read_text()
    return parse_skill_md(content)


def _validate_skill(cache: dict[str, Skill], skill_name: str) -> str:
    skill = cache.get(skill_name)
    if skill is None:
        return f"Skill '{skill_name}' not found."
    try:
        frontmatter, instructions = _load_skill_parts(skill)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        logger.warning("Failed to validate skill %s", skill_name, exc_info=True)
        return f"Error validating skill '{skill_name}'."
    return validate_skill_definition(skill_name, frontmatter, instructions)


def _lint_skill(cache: dict[str, Skill], skill_name: str) -> str:
    skill = cache.get(skill_name)
    if skill is None:
        return f"Skill '{skill_name}' not found."
    try:
        _, instructions = _load_skill_parts(skill)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        logger.warning("Failed to lint skill %s", skill_name, exc_info=True)
        return f"Error linting skill '{skill_name}'."
    return lint_skill_definition(skill_name, instructions)


def skills_instructions(cache: dict[str, Skill]) -> str:
    """Generate a compact system prompt fragment for skill tool discovery."""
    if not cache:
        return ""
    names = ", ".join(sorted(cache.keys()))
    return (
        f"You have skills available: {names}. "
        "Use list_skills to see details, load_skill to get full instructions, "
        "and validate_skill/lint_skill when editing skills."
    )


def create_skills_toolset(
    directories: list[SkillDirectory],
) -> tuple[FunctionToolset[AgentDeps], str]:
    """Create skills tools plus a matching instruction fragment.

    Tools expose progressive disclosure (``load_skill``), safe resource reads,
    and skill authoring quality checks (``validate_skill``/``lint_skill``).
    """
    toolset: FunctionToolset[AgentDeps] = FunctionToolset(
        docstring_format="google",
        require_parameter_descriptions=True,
    )
    skill_meta: dict[str, str] = {"category": "skills"}

    discovered = discover_skills(directories)
    cache: dict[str, Skill] = {s.name: s for s in discovered}

    @toolset.tool(metadata=skill_meta)
    async def list_skills(ctx: RunContext[AgentDeps]) -> str:
        """List available skills with name, description, and tags."""
        return _format_skill_list(cache)

    @toolset.tool(metadata=skill_meta)
    async def load_skill(ctx: RunContext[AgentDeps], skill_name: str) -> str:
        """Load full instructions for a skill by name (progressive disclosure).

        Args:
            skill_name: Name of the skill to load instructions for.
        """
        return load_skill_instructions(cache, skill_name)

    @toolset.tool(metadata=skill_meta)
    async def read_skill_resource(
        ctx: RunContext[AgentDeps],
        skill_name: str,
        resource_name: str,
    ) -> str:
        """Read a resource file from a skill directory.

        Args:
            skill_name: Name of the skill that owns the resource.
            resource_name: Filename of the resource within the skill directory.
        """
        return _read_resource(cache, skill_name, resource_name)

    @toolset.tool(metadata=skill_meta)
    async def validate_skill(ctx: RunContext[AgentDeps], skill_name: str) -> str:
        """Validate SKILL.md frontmatter and required structure.

        Args:
            skill_name: Name of the skill to validate.
        """
        return _validate_skill(cache, skill_name)

    @toolset.tool(metadata=skill_meta)
    async def lint_skill(ctx: RunContext[AgentDeps], skill_name: str) -> str:
        """Lint SKILL.md for common style issues.

        Args:
            skill_name: Name of the skill to lint.
        """
        return _lint_skill(cache, skill_name)

    # Ensure pyright recognizes decorator-registered functions as used
    _ = (list_skills, load_skill, read_skill_resource, validate_skill, lint_skill)

    return toolset, skills_instructions(cache)
