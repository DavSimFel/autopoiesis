"""Tests for chat.py CLI argument parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from chat import _project_version, parse_cli_args


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_parse_cli_args_defaults() -> None:
    args = parse_cli_args(_repo_root(), [])
    assert args.command is None
    assert args.no_approval is False


def test_parse_cli_args_rotate_key_subcommand() -> None:
    args = parse_cli_args(_repo_root(), ["rotate-key"])
    assert args.command == "rotate-key"
    assert args.no_approval is False


def test_parse_cli_args_no_approval_flag() -> None:
    args = parse_cli_args(_repo_root(), ["--no-approval"])
    assert args.command is None
    assert args.no_approval is True


def test_parse_cli_args_version_exits_with_project_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        parse_cli_args(_repo_root(), ["--version"])
    assert exc.value.code == 0

    captured = capsys.readouterr()
    assert _project_version(_repo_root()) in captured.out


def test_project_version_falls_back_when_pyproject_missing(tmp_path: Path) -> None:
    assert _project_version(tmp_path) == "0.1.0"
