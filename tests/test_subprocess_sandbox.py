"""Tests for subprocess sandbox filesystem isolation and resource limits."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import autopoiesis.security.subprocess_sandbox as sandbox_module
from autopoiesis.security.subprocess_sandbox import SubprocessSandboxManager


def test_resolve_cwd_enforces_workspace_boundary(tmp_path: Path) -> None:
    workspace = tmp_path / "agent-a" / "workspace"
    workspace.mkdir(parents=True)
    sandbox = SubprocessSandboxManager(workspace_root=workspace)

    assert sandbox.resolve_cwd("src") == (workspace / "src").resolve()
    with pytest.raises(ValueError, match="escapes allowed roots"):
        sandbox.resolve_cwd("../../etc")


def test_preexec_fn_applies_expected_rlimits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = SubprocessSandboxManager(workspace_root=workspace)

    get_calls: list[int] = []
    set_calls: list[tuple[int, tuple[int, int]]] = []

    monkeypatch.setattr(sandbox_module.resource, "RLIMIT_NPROC", 1, raising=False)
    monkeypatch.setattr(sandbox_module.resource, "RLIMIT_FSIZE", 2, raising=False)
    monkeypatch.setattr(sandbox_module.resource, "RLIMIT_CPU", 3, raising=False)

    def fake_getrlimit(limit: int) -> tuple[int, int]:
        get_calls.append(limit)
        return (0, 1024)

    def fake_setrlimit(limit: int, values: tuple[int, int]) -> None:
        set_calls.append((limit, values))

    monkeypatch.setattr(sandbox_module.resource, "getrlimit", fake_getrlimit)
    monkeypatch.setattr(sandbox_module.resource, "setrlimit", fake_setrlimit)

    sandbox.preexec_fn()()

    assert get_calls == [1, 2, 3]
    assert len(set_calls) == 3
    assert set_calls[0] == (1, (64, 1024))
    assert set_calls[1] == (2, (1024, 1024))
    assert set_calls[2] == (3, (30, 1024))


def test_run_uses_subprocess_with_preexec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = SubprocessSandboxManager(workspace_root=workspace)
    expected = MagicMock()
    run_mock = MagicMock(return_value=expected)
    monkeypatch.setattr(sandbox_module.subprocess, "run", run_mock)

    result = sandbox.run(["git", "status"], cwd=".")

    assert result is expected
    call = run_mock.call_args
    assert call is not None
    assert call.args[0] == ["git", "status"]
    assert call.kwargs["cwd"] == str(workspace.resolve())
    assert callable(call.kwargs["preexec_fn"])
