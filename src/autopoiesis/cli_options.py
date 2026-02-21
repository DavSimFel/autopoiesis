"""CLI argument and version helpers for the autopoiesis entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path


def project_version(repo_root: Path) -> str:
    """Read project version from pyproject.toml, falling back to 0.1.0."""
    toml_path = repo_root / "pyproject.toml"
    if not toml_path.exists():
        return "0.1.0"
    try:
        import tomllib
    except ModuleNotFoundError:  # Python <3.11
        return "0.1.0"
    with open(toml_path, "rb") as fh:
        data = tomllib.load(fh)
    project_data: dict[str, object] = data.get("project", {})
    raw_version: object = project_data.get("version")
    return str(raw_version) if raw_version is not None else "0.1.0"


def parse_cli_args(repo_root: Path, argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(prog="chat", description="Autopoiesis CLI chat")
    parser.add_argument(
        "--version",
        action="version",
        version=project_version(repo_root),
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="Agent identity name (default: $AUTOPOIESIS_AGENT or 'default')",
    )
    parser.add_argument(
        "--no-approval",
        action="store_true",
        help="Skip approval key unlock (dev mode)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to agents.toml config (default: $AUTOPOIESIS_AGENTS_CONFIG)",
    )
    parser.add_argument("command", nargs="?", help="Subcommand: rotate-key | serve | run")
    parser.add_argument("--host", default=None, help="Server bind host (serve mode)")
    parser.add_argument("--port", type=int, default=None, help="Server bind port (serve mode)")
    parser.add_argument("--task", default=None, help="Task string for batch run mode")
    parser.add_argument("--output", default=None, help="Output JSON file path (batch run mode)")
    parser.add_argument(
        "--timeout", type=int, default=None, help="Timeout in seconds (batch run mode)"
    )
    return parser.parse_args(argv)
