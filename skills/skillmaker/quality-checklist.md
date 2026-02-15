# Skill Quality Checklist

- Frontmatter includes `name`, `description`, and `metadata`.
- `name` is kebab-case and stable.
- `metadata.version` uses semver (`x.y.z`).
- `metadata.tags` is a non-empty string list.
- Instructions body starts with `# ` heading.
- Workflow is concrete and actionable.
- No TODO without issue reference (`TODO(#123)`).
- `validate_skill` returns `PASSED`.
- `lint_skill` returns `PASSED` or only acceptable warnings.
