"""Sandboxed skill provider that proxies skill tools via stdio subprocess."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.server.providers import Provider
from fastmcp.server.providers.filesystem import FileSystemProvider
from fastmcp.server.providers.proxy import ProxyProvider

from autopoiesis.security.subprocess_sandbox import SandboxLimits, SubprocessSandboxManager

_SANDBOX_SERVE_FLAG = "--sandbox-serve"


@dataclass(frozen=True)
class SandboxedSkillProvider:
    """Create a FastMCP provider backed by a sandboxed stdio subprocess."""

    skill_server_module: Path
    limits: SandboxLimits = field(default_factory=SandboxLimits)
    workspace_root: Path | None = None
    allowed_roots: tuple[Path, ...] = ()
    _resolved_module: Path = field(init=False, repr=False)
    _sandbox: SubprocessSandboxManager = field(init=False, repr=False)

    def __post_init__(self) -> None:
        module_path = self.skill_server_module.expanduser().resolve()
        root = self._resolve_workspace_root(module_path)
        sandbox = SubprocessSandboxManager(
            workspace_root=root,
            allowed_roots=self.allowed_roots,
            limits=self.limits,
        )
        resolved_module = sandbox.path_validator.ensure_file(module_path)
        object.__setattr__(self, "_resolved_module", resolved_module)
        object.__setattr__(self, "_sandbox", sandbox)

    @property
    def sandbox(self) -> SubprocessSandboxManager:
        """Public accessor for the sandbox manager."""
        return self._sandbox

    def get_provider(self) -> Provider:
        """Return a proxy provider that talks to the sandboxed child over stdio."""

        def _client_factory() -> Client[Any]:
            transport = StdioTransport(
                command=sys.executable,
                args=self._launcher_args(),
                cwd=str(self._sandbox.resolve_cwd(self._resolved_module.parent)),
                env=self._launcher_env(),
                keep_alive=False,
            )
            return Client(transport)

        return ProxyProvider(_client_factory)

    def _launcher_args(self) -> list[str]:
        limits = self.limits
        return [
            "-m",
            "autopoiesis.skills.sandboxed_provider",
            _SANDBOX_SERVE_FLAG,
            "--module",
            str(self._resolved_module),
            "--workspace-root",
            str(self._sandbox.path_validator.workspace_root),
            "--max-processes",
            str(limits.max_processes),
            "--max-file-size-bytes",
            str(limits.max_file_size_bytes),
            "--max-cpu-seconds",
            str(limits.max_cpu_seconds),
        ]

    def _launcher_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _resolve_workspace_root(self, module_path: Path) -> Path:
        if self.workspace_root is None:
            return module_path.parent
        return self.workspace_root.expanduser().resolve()


async def serve_sandboxed_skill(
    *,
    module_path: Path,
    workspace_root: Path,
    limits: SandboxLimits,
) -> None:
    """Launch a file-scoped FastMCP server with sandbox limits applied."""
    sandbox = SubprocessSandboxManager(workspace_root=workspace_root, limits=limits)
    resolved_module = sandbox.path_validator.ensure_file(module_path)

    # Apply RLIMIT controls to this process before serving MCP over stdio.
    sandbox.preexec_fn()()

    mcp = FastMCP(f"sandboxed-{resolved_module.parent.name}")
    mcp.add_provider(FileSystemProvider(root=resolved_module.parent))
    await mcp.run_stdio_async()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autopoiesis.skills.sandboxed_provider")
    parser.add_argument(_SANDBOX_SERVE_FLAG, action="store_true")
    parser.add_argument("--module", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--max-processes", type=int, default=SandboxLimits().max_processes)
    parser.add_argument(
        "--max-file-size-bytes",
        type=int,
        default=SandboxLimits().max_file_size_bytes,
    )
    parser.add_argument("--max-cpu-seconds", type=int, default=SandboxLimits().max_cpu_seconds)
    return parser


def _run_from_cli(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.sandbox_serve:
        parser.error("Missing sandbox serve mode flag.")

    if args.module is None:
        parser.error("--module is required in sandbox serve mode.")
    if args.workspace_root is None:
        parser.error("--workspace-root is required in sandbox serve mode.")

    limits = SandboxLimits(
        max_processes=args.max_processes,
        max_file_size_bytes=args.max_file_size_bytes,
        max_cpu_seconds=args.max_cpu_seconds,
    )
    asyncio.run(
        serve_sandboxed_skill(
            module_path=args.module,
            workspace_root=args.workspace_root,
            limits=limits,
        )
    )
    return 0


def _main() -> int:
    try:
        return _run_from_cli()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
