"""Tests for allowlist-based workspace path validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopoiesis.security.path_validator import PathValidator


def test_resolve_path_blocks_workspace_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    validator = PathValidator(workspace_root=workspace)

    with pytest.raises(ValueError, match="escapes allowed roots"):
        validator.resolve_path("../outside.txt")


def test_resolve_path_allows_workspace_subpath(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)
    validator = PathValidator(workspace_root=workspace)

    resolved = validator.resolve_path("nested")
    assert resolved == nested.resolve()


def test_allowlist_supports_extra_roots(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    extra = tmp_path / "shared"
    extra.mkdir()
    validator = PathValidator(workspace_root=workspace, allowed_roots=(extra,))

    resolved = validator.resolve_path(extra)
    assert resolved == extra.resolve()


def test_ensure_file_requires_existing_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    validator = PathValidator(workspace_root=workspace)

    with pytest.raises(ValueError, match="not a file"):
        validator.ensure_file("missing.txt")
