---
name: skillmaker
description: Create and maintain high-quality skills with built-in lint and validation tools.
metadata:
  version: 1.0.0
  tags:
    - skills
    - tooling
    - quality
  author: autopoiesis
---

# Skillmaker

Use this skill when creating or updating `SKILL.md`-based capabilities.

## Workflow

1. Inspect existing skills using `list_skills`.
2. Draft or update a skill using the template resource.
3. Run `validate_skill(skill_name)` to enforce metadata and required structure.
4. Run `lint_skill(skill_name)` to catch style issues.
5. Repeat until validation and lint both pass.

## Resources

- `skill-template.md` for new skill scaffolding
- `quality-checklist.md` for release readiness checks

## Notes

- Keep skill names kebab-case.
- Keep frontmatter explicit (`name`, `description`, `metadata.version`, `metadata.tags`).
- Add issue references for TODOs using `TODO(#123)`.
