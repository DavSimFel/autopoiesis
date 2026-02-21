"""Tests for path validation helpers used in tool gating."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopoiesis.security.path_validator import PathValidator


@pytest.fixture
def validator(tmp_path: Path) -> PathValidator:
    return PathValidator(workspace_root=tmp_path)


class TestPathValidatorToolIntegration:
    """Verify PathValidator works as a tool-call gate."""

    def test_valid_path_resolves(self, validator: PathValidator, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.touch()
        resolved = validator.resolve_path(str(target))
        assert resolved == target.resolve()

    def test_escaping_path_raises(self, validator: PathValidator) -> None:
        with pytest.raises(ValueError, match="escapes"):
            validator.resolve_path("/etc/passwd")

    def test_relative_path_within_workspace(self, validator: PathValidator, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        resolved = validator.resolve_path("sub")
        assert resolved == (tmp_path / "sub").resolve()

    def test_dotdot_escape_blocked(self, validator: PathValidator) -> None:
        with pytest.raises(ValueError, match="escapes"):
            validator.resolve_path("../../etc/passwd")

    def test_extra_allowed_roots(self, tmp_path: Path) -> None:
        extra = tmp_path / "extra"
        extra.mkdir()
        ws = tmp_path / "ws"
        ws.mkdir()
        v = PathValidator(workspace_root=ws, allowed_roots=(extra,))
        assert v.is_allowed(extra / "file.txt")
