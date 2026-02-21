"""Tests for SandboxedSkillProvider."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autopoiesis.security.subprocess_sandbox import SandboxLimits
from autopoiesis.skills.sandboxed_provider import SandboxedSkillProvider


def _write_skill_server(skill_dir: Path) -> Path:
    skill_dir.mkdir(parents=True, exist_ok=True)
    server_py = skill_dir / "server.py"
    server_py.write_text(
        """\
from fastmcp import FastMCP
mcp = FastMCP("test_skill")

@mcp.tool()
def ping(message: str) -> str:
    return f"pong: {message}"
"""
    )
    return server_py


class TestSandboxedSkillConfig:
    def test_defaults(self, tmp_path: Path) -> None:
        sp = _write_skill_server(tmp_path / "skill")
        provider = SandboxedSkillProvider(skill_server_module=sp, workspace_root=sp.parent)
        assert provider.sandbox is not None

    def test_custom_limits(self, tmp_path: Path) -> None:
        sp = _write_skill_server(tmp_path / "skill")
        limits = SandboxLimits(max_processes=128, max_file_size_bytes=8192, max_cpu_seconds=10)
        provider = SandboxedSkillProvider(
            skill_server_module=sp,
            limits=limits,
            workspace_root=sp.parent,
        )
        assert provider.limits.max_processes == 128

    def test_invalid_module_path(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a file"):
            SandboxedSkillProvider(
                skill_server_module=tmp_path / "nonexistent.py",
                workspace_root=tmp_path,
            )


class TestSandboxedSkillProviderExec:
    def test_sandbox_runs_command(self, tmp_path: Path) -> None:
        sp = _write_skill_server(tmp_path / "skill")
        provider = SandboxedSkillProvider(skill_server_module=sp, workspace_root=sp.parent)
        result = provider.sandbox.run(["echo", "hello"], cwd=sp.parent)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_sandbox_enforces_cwd(self, tmp_path: Path) -> None:
        sp = _write_skill_server(tmp_path / "skill")
        provider = SandboxedSkillProvider(skill_server_module=sp, workspace_root=sp.parent)
        result = provider.sandbox.run(["pwd"], cwd=sp.parent)
        assert str(sp.parent.resolve()) in result.stdout

    def test_sandbox_reports_limits(self, tmp_path: Path) -> None:
        sp = _write_skill_server(tmp_path / "skill")
        limits = SandboxLimits(max_file_size_bytes=4096, max_cpu_seconds=5)
        provider = SandboxedSkillProvider(
            skill_server_module=sp,
            limits=limits,
            workspace_root=sp.parent,
        )
        result = provider.sandbox.run(
            [
                "python3",
                "-c",
                "import resource,json; "
                "f,_=resource.getrlimit(resource.RLIMIT_FSIZE); "
                "c,_=resource.getrlimit(resource.RLIMIT_CPU); "
                "print(json.dumps({'fsize':f,'cpu':c}))",
            ],
            cwd=sp.parent,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout.strip())
        assert payload["fsize"] <= 4096
        assert payload["cpu"] <= 5

    def test_get_provider_returns_provider(self, tmp_path: Path) -> None:
        sp = _write_skill_server(tmp_path / "skill")
        provider = SandboxedSkillProvider(skill_server_module=sp, workspace_root=sp.parent)
        proxy = provider.get_provider()
        assert proxy is not None

    def test_extra_allowed_roots(self, tmp_path: Path) -> None:
        extra = tmp_path / "extra"
        extra.mkdir()
        sp = _write_skill_server(tmp_path / "skill")
        provider = SandboxedSkillProvider(
            skill_server_module=sp,
            workspace_root=sp.parent,
            allowed_roots=(extra,),
        )
        assert provider.sandbox.path_validator.is_allowed(extra / "file.txt")
