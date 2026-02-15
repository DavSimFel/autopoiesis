"""Filesystem-based skill system with progressive disclosure.

Skills are folders containing a ``SKILL.md`` with YAML frontmatter (metadata)
and markdown body (instructions). The agent discovers skills at startup by
scanning frontmatter only — full instructions are loaded on demand to keep
token usage low.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
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
    if not content.startswith("---"):
        return {}, content.strip()

    end = content.find("---", 3)
    if end == -1:
        return {}, content.strip()

    frontmatter_yaml = content[3:end].strip()
    instructions = content[end + 3 :].strip()

    frontmatter: dict[str, Any] = yaml.safe_load(frontmatter_yaml) or {}
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
            except Exception:
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
    if skill_name not in cache:
        return f"Skill '{skill_name}' not found."

    skill = cache[skill_name]
    resource_path = (skill.path / resource_name).resolve()
    skill_dir_resolved = skill.path.resolve()

    # Security: prevent path traversal outside the skill directory
    if not resource_path.is_relative_to(skill_dir_resolved):
        return "Error: resource path escapes skill directory."

    if not resource_path.exists():
        return f"Resource '{resource_name}' not found. Available: {skill.resources}"

    return resource_path.read_text()


def create_skills_toolset(
    directories: list[SkillDirectory],
) -> FunctionToolset[AgentDeps]:
    """Create a PydanticAI toolset for skill discovery and loading.

    Tools:
    - ``list_skills`` — show available skills (name, description, tags)
    - ``load_skill`` — load full instructions for a skill (progressive disclosure)
    - ``read_skill_resource`` — read a resource file bundled with a skill
    """
    toolset: FunctionToolset[AgentDeps] = FunctionToolset()

    discovered = discover_skills(directories)
    # TODO: cache invalidation / refresh mechanism
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

    return toolset
