"""Durable CLI chat entrypoint with DBOS-backed queue execution."""

from __future__ import annotations

import argparse
import os
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai.messages import ModelMessage

import otel_tracing
from approval_keys import ApprovalKeyManager
from approval_policy import ToolPolicyRegistry
from approval_store import ApprovalStore
from chat_cli import cli_chat_loop
from chat_runtime import (
    AgentOptions,
    Runtime,
    build_agent,
    build_backend,
    build_toolsets,
    instrument_agent,
    resolve_workspace_root,
    set_runtime,
)
from chat_worker import checkpoint_history_processor
from context_manager import compact_history
from history_store import (
    cleanup_stale_checkpoints,
    init_history_store,
    resolve_history_db_path,
)
from memory_store import init_memory_store, resolve_memory_db_path
from subscription_processor import materialize_subscriptions
from subscriptions import SubscriptionRegistry
from tool_result_truncation import truncate_tool_results

try:
    from dbos import DBOS, DBOSConfig
except ModuleNotFoundError as exc:
    missing_package = exc.name or "unknown package"
    raise SystemExit(
        f"Missing DBOS dependency package `{missing_package}`. Run `uv sync` so "
        "`pydantic-ai-slim[dbos,mcp]` and `dbos` are installed."
    ) from exc


def _truncate_processor(msgs: list[ModelMessage]) -> list[ModelMessage]:
    """Truncate oversized tool results in message history."""
    return truncate_tool_results(msgs, resolve_workspace_root())


def _compact_processor(msgs: list[ModelMessage]) -> list[ModelMessage]:
    """Compact older messages when token usage exceeds threshold."""
    return compact_history(msgs)


def _rotate_key(base_dir: Path) -> None:
    """Rotate active approval signing key and expire pending envelopes."""
    approval_store = ApprovalStore.from_env(base_dir=base_dir)
    key_manager = ApprovalKeyManager.from_env(base_dir=base_dir)
    key_manager.rotate_key_interactive(
        expire_pending_envelopes=approval_store.expire_pending_envelopes
    )
    print("Approval signing key rotated. Pending approvals were expired.")


@dataclass(frozen=True)
class CliArgs:
    """Parsed command-line arguments."""

    command: str | None
    no_approval: bool


def _project_version(base_dir: Path) -> str:
    """Read package version from pyproject.toml with a stable fallback."""
    pyproject_path = base_dir / "pyproject.toml"
    try:
        pyproject_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return "0.1.0"
    project_data = pyproject_data.get("project")
    if isinstance(project_data, dict):
        version = project_data.get("version")
        if isinstance(version, str) and version:
            return version
    return "0.1.0"


def parse_cli_args(base_dir: Path, argv: Sequence[str] | None = None) -> CliArgs:
    """Parse CLI flags and subcommands."""
    parser = argparse.ArgumentParser(
        prog="chat.py",
        description="Durable CLI chat with DBOS-backed execution.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_project_version(base_dir)}",
    )
    parser.add_argument(
        "--no-approval",
        action="store_true",
        help="Disable deferred tool approvals for write/shell tool calls.",
    )
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser(
        "rotate-key",
        help="Rotate the approval signing key and expire pending approvals.",
    )
    parsed = parser.parse_args(argv)
    command = parsed.command if isinstance(parsed.command, str) else None
    return CliArgs(command=command, no_approval=bool(parsed.no_approval))


def main() -> None:
    """Load config, assemble runtime components, and launch DBOS + CLI chat."""
    base_dir = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=base_dir / ".env")
    otel_tracing.configure()

    cli_args = parse_cli_args(base_dir)
    if cli_args.command == "rotate-key":
        _rotate_key(base_dir)
        return

    provider = os.getenv("AI_PROVIDER", "anthropic").lower()
    agent_name = os.getenv("DBOS_AGENT_NAME", "chat")

    backend = build_backend()
    approval_store = ApprovalStore.from_env(base_dir=base_dir)
    key_manager = ApprovalKeyManager.from_env(base_dir=base_dir)
    if not cli_args.no_approval:
        key_manager.ensure_unlocked_interactive()
    tool_policy = ToolPolicyRegistry.default()
    memory_db_path = resolve_memory_db_path(
        os.getenv("DBOS_SYSTEM_DATABASE_URL", "sqlite:///dbostest.sqlite")
    )
    init_memory_store(memory_db_path)
    workspace_root = resolve_workspace_root()
    sub_db_path = str(Path(memory_db_path).with_name("subscriptions.sqlite"))
    subscription_registry = SubscriptionRegistry(sub_db_path)
    toolsets, system_prompt = build_toolsets(
        memory_db_path=memory_db_path,
        subscription_registry=subscription_registry,
        require_write_approval=not cli_args.no_approval,
    )

    def _subscription_processor(msgs: list[ModelMessage]) -> list[ModelMessage]:
        return materialize_subscriptions(
            msgs,
            subscription_registry,
            workspace_root,
            memory_db_path,
        )

    agent = build_agent(
        provider,
        agent_name,
        toolsets,
        system_prompt,
        options=AgentOptions(
            history_processors=[
                _truncate_processor,
                _compact_processor,
                _subscription_processor,
                checkpoint_history_processor,
            ],
        ),
    )
    instrument_agent(agent)
    system_database_url = os.getenv(
        "DBOS_SYSTEM_DATABASE_URL",
        "sqlite:///dbostest.sqlite",
    )
    history_db_path = resolve_history_db_path(system_database_url)
    init_history_store(history_db_path)
    cleanup_stale_checkpoints(history_db_path)
    set_runtime(
        Runtime(
            agent=agent,
            backend=backend,
            history_db_path=history_db_path,
            memory_db_path=memory_db_path,
            subscription_registry=subscription_registry,
            approval_store=approval_store,
            key_manager=key_manager,
            tool_policy=tool_policy,
        )
    )

    dbos_config: DBOSConfig = {
        "name": os.getenv("DBOS_APP_NAME", "pydantic_dbos_agent"),
        "system_database_url": system_database_url,
    }
    DBOS(config=dbos_config)
    DBOS.launch()
    cli_chat_loop()


if __name__ == "__main__":
    main()
