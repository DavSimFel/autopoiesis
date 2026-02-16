"""Durable CLI chat entrypoint with DBOS-backed queue execution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from approval_keys import ApprovalKeyManager
from approval_policy import ToolPolicyRegistry
from approval_store import ApprovalStore
from chat_cli import cli_chat_loop
from chat_runtime import Runtime, build_agent, build_backend, build_toolsets, set_runtime
from chat_worker import checkpoint_history_processor
from history_store import (
    cleanup_stale_checkpoints,
    init_history_store,
    resolve_history_db_path,
)
from memory_store import init_memory_store, resolve_memory_db_path

try:
    from dbos import DBOS, DBOSConfig
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing DBOS dependencies. Run `uv sync` so "
        "`pydantic-ai-slim[dbos,mcp]` and `dbos` are installed."
    ) from exc


def _rotate_key(base_dir: Path) -> None:
    """Rotate active approval signing key and expire pending envelopes."""
    approval_store = ApprovalStore.from_env(base_dir=base_dir)
    key_manager = ApprovalKeyManager.from_env(base_dir=base_dir)
    key_manager.rotate_key_interactive(
        expire_pending_envelopes=approval_store.expire_pending_envelopes
    )
    print("Approval signing key rotated. Pending approvals were expired.")


def _handle_subcommand(base_dir: Path) -> bool:
    """Handle CLI subcommands. Returns True if a subcommand ran."""
    args = sys.argv[1:]
    if not args:
        return False
    if len(args) == 1 and args[0] == "rotate-key":
        _rotate_key(base_dir)
        return True
    raise SystemExit("Usage: python chat.py [rotate-key]")


def main() -> None:
    """Load config, assemble runtime components, and launch DBOS + CLI chat."""
    base_dir = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=base_dir / ".env")

    if _handle_subcommand(base_dir):
        return

    provider = os.getenv("AI_PROVIDER", "anthropic").lower()
    agent_name = os.getenv("DBOS_AGENT_NAME", "chat")

    backend = build_backend()
    approval_store = ApprovalStore.from_env(base_dir=base_dir)
    key_manager = ApprovalKeyManager.from_env(base_dir=base_dir)
    key_manager.ensure_unlocked_interactive()
    tool_policy = ToolPolicyRegistry.default()
    memory_db_path = resolve_memory_db_path(
        os.getenv("DBOS_SYSTEM_DATABASE_URL", "sqlite:///dbostest.sqlite")
    )
    init_memory_store(memory_db_path)
    toolsets, instructions = build_toolsets(memory_db_path=memory_db_path)
    agent = build_agent(
        provider,
        agent_name,
        toolsets,
        instructions,
        history_processors=[checkpoint_history_processor],
    )
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
