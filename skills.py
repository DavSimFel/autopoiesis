"""Filesystem-based skill system with progressive disclosure.

Skills are folders containing a ``SKILL.md`` with YAML frontmatter (metadata)
and markdown body (instructions). The agent discovers skills at startup by
scanning frontmatter only — full instructions are loaded on demand to keep
token usage low.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from models import AgentDeps

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SkillDirectory(BaseModel):
    """A directory to scan for skills."""

    path: Path
    recursive: bool = True


class Skill(BaseModel):
    """Skill metadata with lazy-loaded instructions.

    ``instructions`` is ``None`` until ``load_skill()`` is called. This is
    the progressive disclosure pattern — the agent sees only the 1-line
    description until it explicitly loads the full instructions.
    """

    name: str
    description: str
    path: Path
    tags: list[str] = []
    version: str = "1.0.0"
    author: str = ""
    resources: list[str] = []
    instructions: str | None = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_skill_md(content: str) -> tuple[dict[str, Any], str]:
    """Parse a SKILL.md file into ``(frontmatter_dict, instructions_markdown)``.

    Expects optional YAML frontmatter delimited by ``---``. If no frontmatter
    is present, returns an empty dict and the full content as instructions.
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

    loaded_frontmatter: Any = yaml.safe_load(frontmatter_yaml) if frontmatter_yaml else {}
    if not isinstance(loaded_frontmatter, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping.")
    frontmatter = cast(dict[str, Any], loaded_frontmatter)
    return frontmatter, instructions


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_skills(directories: list[SkillDirectory]) -> list[Skill]:
    """Walk skill directories and build skill metadata from frontmatter only.

    Returns an empty list if directories are missing or contain no valid
    skills. Never raises on individual skill parse failures — logs a warning
    and continues.
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
                if not frontmatter.get("name"):
                    continue

                skill_folder = skill_file.parent
                resources = [
                    str(f.relative_to(skill_folder))
                    for f in skill_folder.iterdir()
                    if f.is_file() and f.name != "SKILL.md"
                ]

                skills.append(
                    Skill(
                        name=frontmatter["name"],
                        description=frontmatter.get("description", ""),
                        path=skill_folder,
                        tags=frontmatter.get("tags", []),
                        version=frontmatter.get("version", "1.0.0"),
                        author=frontmatter.get("author", ""),
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


# ---------------------------------------------------------------------------
# Toolset
# ---------------------------------------------------------------------------


def _format_skill_list(cache: dict[str, Skill]) -> str:
    """Format the skill cache into a human-readable list."""
    if not cache:
        return "No skills available."
    lines = ["Available Skills:", ""]
    for name, skill in sorted(cache.items()):
        tags = ", ".join(skill.tags) if skill.tags else "none"
        lines.append(f"- **{name}** (v{skill.version}): {skill.description} [{tags}]")
    return "\n".join(lines)


def _load_skill_instructions(cache: dict[str, Skill], skill_name: str) -> str:
    """Load and return full instructions for a skill, caching for future calls."""
    if skill_name not in cache:
        available = ", ".join(sorted(cache.keys())) if cache else "none"
        return f"Skill '{skill_name}' not found. Available: {available}"

    skill = cache[skill_name]
    if skill.instructions is None:
        skill_file = skill.path / "SKILL.md"
        if not skill_file.exists():
            return f"SKILL.md not found at {skill.path}"
        content = skill_file.read_text()
        _, skill.instructions = parse_skill_md(content)

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


def skills_instructions(cache: dict[str, Skill]) -> str:
    """Generate a system prompt fragment listing available skills.

    Returns an empty string when no skills are discovered, so it contributes
    nothing to the system prompt.
    """
    if not cache:
        return ""
    names = ", ".join(sorted(cache.keys()))
    return (
        f"You have skills available: {names}. "
        "Use list_skills to see details, load_skill to get full instructions."
    )


def create_skills_toolset(
    directories: list[SkillDirectory],
) -> tuple[FunctionToolset[AgentDeps], str]:
    """Create a PydanticAI toolset and instructions for skill discovery and loading.

    Returns a ``(toolset, instructions_text)`` tuple. The instructions text is
    a system prompt fragment listing discovered skill names — pass it to the
    agent's ``instructions`` parameter alongside other instruction sources.

    Tools:
    - ``list_skills`` — show available skills (name, description, tags)
    - ``load_skill`` — load full instructions for a skill (progressive disclosure)
    - ``read_skill_resource`` — read a resource file bundled with a skill
    """
    toolset: FunctionToolset[AgentDeps] = FunctionToolset()

    discovered = discover_skills(directories)
    cache: dict[str, Skill] = {s.name: s for s in discovered}

    @toolset.tool
    async def list_skills(ctx: RunContext[AgentDeps]) -> str:
        """List available skills with name, description, and tags."""
        return _format_skill_list(cache)

    @toolset.tool
    async def load_skill(ctx: RunContext[AgentDeps], skill_name: str) -> str:
        """Load full instructions for a skill by name (progressive disclosure)."""
        return _load_skill_instructions(cache, skill_name)

    @toolset.tool
    async def read_skill_resource(
        ctx: RunContext[AgentDeps],
        skill_name: str,
        resource_name: str,
    ) -> str:
        """Read a resource file from a skill directory."""
        return _read_resource(cache, skill_name, resource_name)

    # Ensure pyright recognizes decorator-registered functions as used
    _ = (list_skills, load_skill, read_skill_resource)

    return toolset, skills_instructions(cache)
