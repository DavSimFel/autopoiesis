"""FastMCP server for the skillmaker skill.

Exposes SKILL.md validation and lint tools via the FastMCP MCP endpoint.
Tools are tagged with ``skillmaker`` so they can be lazily enabled/disabled
via Visibility transforms on the parent server.
"""

from __future__ import annotations

from fastmcp.tools import tool


@tool(tags={"skillmaker"})
def validate(skill_name: str, frontmatter_yaml: str, instructions: str) -> str:
    """Validate a SKILL.md's metadata structure and content.

    Checks required frontmatter fields (name, description, metadata.version,
    metadata.tags), validates name format (kebab-case), and verifies that
    instructions start with a level-1 heading.

    Args:
        skill_name: Name of the skill being validated (used in the report header).
        frontmatter_yaml: YAML frontmatter block as a string (without ``---`` delimiters).
        instructions: Instructions body from the SKILL.md (everything after the frontmatter).
    """
    import yaml

    from autopoiesis.skills.skillmaker_tools import validate_skill_definition

    try:
        loaded: object = yaml.safe_load(frontmatter_yaml) if frontmatter_yaml.strip() else {}
    except yaml.YAMLError as exc:
        return f"Invalid YAML frontmatter: {exc}"
    if not isinstance(loaded, dict):
        return "Frontmatter must be a YAML mapping."
    return validate_skill_definition(skill_name, loaded, instructions)


@tool(tags={"skillmaker"})
def lint(skill_name: str, instructions: str) -> str:
    """Lint a skill's instructions body for style issues.

    Checks for tab characters, lines exceeding 100 characters, trailing
    whitespace, and TODO markers without issue references.

    Args:
        skill_name: Name of the skill being linted (used in the report header).
        instructions: Instructions body from the SKILL.md (everything after the frontmatter).
    """
    from autopoiesis.skills.skillmaker_tools import lint_skill_definition

    return lint_skill_definition(skill_name, instructions)
