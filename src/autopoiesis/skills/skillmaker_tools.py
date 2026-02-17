"""Linting and validation helpers for SKILL.md files."""

from __future__ import annotations

import re
from typing import Any, cast

_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_MAX_LINE_LENGTH = 100
_MAX_LISTED_LINES = 8
_SUPPORTED_SKILL_KEYS = {
    "argument-hint",
    "compatibility",
    "description",
    "disable-model-invocation",
    "license",
    "metadata",
    "name",
    "user-invokable",
}
_REQUIRED_METADATA_KEYS = {"version", "tags"}


def extract_skill_metadata(frontmatter: dict[str, Any]) -> tuple[str, list[str], str, str]:
    """Extract normalized description/tags/version/author values from frontmatter."""
    metadata = _metadata_map(frontmatter.get("metadata"))

    description_raw = frontmatter.get("description", "")
    description = description_raw if isinstance(description_raw, str) else ""

    tags_raw = metadata.get("tags", [])
    tags: list[str] = []
    if isinstance(tags_raw, list):
        for tag in cast(list[object], tags_raw):
            if isinstance(tag, str) and tag:
                tags.append(tag)

    version_raw = metadata.get("version", "1.0.0")
    version = version_raw if isinstance(version_raw, str) else "1.0.0"

    author_raw = metadata.get("author", "")
    author = author_raw if isinstance(author_raw, str) else ""
    return description, tags, version, author


def validate_skill_definition(
    skill_name: str,
    frontmatter: dict[str, Any],
    instructions: str,
) -> str:
    """Validate required SKILL.md structure and metadata semantics."""
    metadata = _metadata_map(frontmatter.get("metadata"))
    errors = [
        *_validate_supported_keys(frontmatter),
        *_validate_required_metadata_keys(metadata),
        *_validate_name(frontmatter.get("name")),
        *_validate_description(frontmatter.get("description")),
        *_validate_tags(metadata.get("tags")),
        *_validate_version(metadata.get("version")),
        *_validate_instructions(instructions),
    ]

    if errors:
        return _format_report(f"Skill validation FAILED: {skill_name}", errors)
    return f"Skill validation PASSED: {skill_name}"


def lint_skill_definition(skill_name: str, instructions: str) -> str:
    """Run lightweight style lint checks for SKILL.md content."""
    warnings: list[str] = []
    lines = instructions.splitlines()
    long_lines = [idx for idx, line in enumerate(lines, start=1) if len(line) > _MAX_LINE_LENGTH]
    trailing_ws = [idx for idx, line in enumerate(lines, start=1) if line.rstrip() != line]

    if "\t" in instructions:
        warnings.append("Use spaces instead of tab characters.")
    if long_lines:
        warnings.append(
            "Line length exceeds 100 characters at lines: " + _format_line_numbers(long_lines)
        )
    if trailing_ws:
        warnings.append("Trailing whitespace found at lines: " + _format_line_numbers(trailing_ws))
    if "TODO" in instructions and "TODO(#" not in instructions:
        warnings.append("TODOs should include issue references (`TODO(#123)`).")

    if warnings:
        return _format_report(f"Skill lint WARNINGS: {skill_name}", warnings)
    return f"Skill lint PASSED: {skill_name}"


def _validate_name(name: Any) -> list[str]:
    if not isinstance(name, str) or not name.strip():
        return ["Frontmatter `name` is required."]
    if not _SKILL_NAME_PATTERN.fullmatch(name):
        return ["Frontmatter `name` must use kebab-case letters/numbers."]
    return []


def _validate_description(description: Any) -> list[str]:
    if not isinstance(description, str) or not description.strip():
        return ["Frontmatter `description` is required."]
    return []


def _validate_tags(tags_raw: Any) -> list[str]:
    if not isinstance(tags_raw, list):
        return ["Frontmatter `metadata.tags` must be a list of non-empty strings."]
    if not tags_raw:
        return ["Frontmatter `metadata.tags` must include at least one tag."]
    tags = cast(list[object], tags_raw)
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            return ["Frontmatter `metadata.tags` must be a list of non-empty strings."]
    return []


def _validate_version(version: Any) -> list[str]:
    if not isinstance(version, str) or not _SEMVER_PATTERN.fullmatch(version):
        return ["Frontmatter `metadata.version` must use semver (for example `1.0.0`)."]
    return []


def _validate_instructions(instructions: str) -> list[str]:
    if not instructions.strip():
        return ["Instructions body must not be empty."]
    if not instructions.lstrip().startswith("# "):
        return ["Instructions should start with a level-1 heading (`# ...`)."]
    return []


def _format_report(header: str, items: list[str]) -> str:
    lines = [header]
    lines.extend(f"- {item}" for item in items)
    return "\n".join(lines)


def _format_line_numbers(values: list[int]) -> str:
    shown = values[:_MAX_LISTED_LINES]
    suffix = "" if len(values) <= _MAX_LISTED_LINES else ", ..."
    return ", ".join(str(value) for value in shown) + suffix


def _metadata_map(metadata_raw: Any) -> dict[str, Any]:
    if isinstance(metadata_raw, dict):
        return cast(dict[str, Any], metadata_raw)
    return {}


def _validate_required_metadata_keys(metadata: dict[str, Any]) -> list[str]:
    missing = sorted(_REQUIRED_METADATA_KEYS - set(metadata.keys()))
    if not missing:
        return []
    return ["Frontmatter `metadata` must include keys: version, tags."]


def _validate_supported_keys(frontmatter: dict[str, Any]) -> list[str]:
    unsupported = sorted(set(frontmatter) - _SUPPORTED_SKILL_KEYS)
    if unsupported:
        return [
            "Unsupported frontmatter keys: "
            + ", ".join(unsupported)
            + ". Use `metadata` for custom fields."
        ]
    return []
