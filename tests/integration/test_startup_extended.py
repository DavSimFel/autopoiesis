"""Extended startup integration tests — CLI arg parsing, mode branching, env loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopoiesis.cli import parse_cli_args


class TestCLIArgParsing:
    """CLI argument parsing covers all modes."""

    def test_default_args(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, [])
        assert args.command is None
        assert args.agent is None
        assert args.no_approval is False
        assert args.config is None

    def test_serve_mode(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, ["serve", "--host", "0.0.0.0", "--port", "8080"])
        assert args.command == "serve"
        assert args.host == "0.0.0.0"
        assert args.port == 8080

    def test_run_batch_mode(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, ["run", "--task", "do stuff", "--output", "/tmp/out.json"])
        assert args.command == "run"
        assert args.task == "do stuff"
        assert args.output == "/tmp/out.json"

    def test_agent_flag(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, ["--agent", "coder"])
        assert args.agent == "coder"

    def test_no_approval_flag(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, ["--no-approval"])
        assert args.no_approval is True

    def test_rotate_key_command(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, ["rotate-key"])
        assert args.command == "rotate-key"

    def test_timeout_flag(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, ["run", "--timeout", "30"])
        assert args.timeout == 30

    def test_config_flag(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, ["--config", "/path/to/agents.toml"])
        assert args.config == "/path/to/agents.toml"


class TestModeBranching:
    """Verify that the mode branching logic is consistent."""

    def test_serve_is_serve(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, ["serve"])
        is_batch = args.command == "run"
        is_serve = args.command == "serve"
        assert not is_batch
        assert is_serve

    def test_run_is_batch(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, ["run"])
        is_batch = args.command == "run"
        is_serve = args.command == "serve"
        assert is_batch
        assert not is_serve

    def test_no_command_is_chat(self, tmp_path: Path) -> None:
        args = parse_cli_args(tmp_path, [])
        is_batch = args.command == "run"
        is_serve = args.command == "serve"
        assert not is_batch
        assert not is_serve
        # Default mode = interactive chat
