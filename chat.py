"""Durable CLI chat entrypoint with DBOS-backed queue execution."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai.messages import ModelMessage

from agent.cli import cli_chat_loop
from agent.context import compact_history
from agent.runtime import (
    AgentOptions,
    Runtime,
    build_agent,
    instrument_agent,
    set_runtime,
)
from agent.truncation import truncate_tool_results
from agent.worker import checkpoint_history_processor
from approval.keys import ApprovalKeyManager
from approval.policy import ToolPolicyRegistry
from approval.store import ApprovalStore
from infra import otel_tracing
from infra.subscription_processor import materialize_subscriptions
from infra.topic_processor import inject_topic_context
from model_resolution import resolve_provider
from store.history import (
    cleanup_stale_checkpoints,
    init_history_store,
    resolve_history_db_path,
)
from store.knowledge import (
    ensure_journal_entry,
    init_knowledge_index,
    load_knowledge_context,
    reindex_knowledge,
)
from store.memory import init_memory_store, resolve_memory_db_path
from store.subscriptions import SubscriptionRegistry
from toolset_builder import build_backend, build_toolsets, resolve_workspace_root
from topic_manager import TopicRegistry

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


def _project_version(repo_root: Path) -> str:
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


def parse_cli_args(repo_root: Path, argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(prog="chat", description="Autopoiesis CLI chat")
    parser.add_argument(
        "--version",
        action="version",
        version=_project_version(repo_root),
    )
    parser.add_argument(
        "--no-approval",
        action="store_true",
        help="Skip approval key unlock (dev mode)",
    )
    parser.add_argument("command", nargs="?", help="Subcommand: rotate-key | serve | run")
    parser.add_argument("--host", default=None, help="Server bind host (serve mode)")
    parser.add_argument("--port", type=int, default=None, help="Server bind port (serve mode)")
    parser.add_argument("--task", default=None, help="Task string for batch run mode")
    parser.add_argument("--output", default=None, help="Output JSON file path (batch run mode)")
    parser.add_argument(
        "--timeout", type=int, default=None, help="Timeout in seconds (batch run mode)"
    )
    return parser.parse_args(argv if argv is not None else sys.argv[1:])


def main() -> None:
    """Load config, assemble runtime components, and launch DBOS + CLI chat."""
    base_dir = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=base_dir / ".env")
    otel_tracing.configure()

    args = parse_cli_args(base_dir)
    if args.command == "rotate-key":
        _rotate_key(base_dir)
        return

    if args.command == "serve":
        from server.cli import run_server

        run_server(host=args.host, port=args.port)
        return

    is_batch = args.command == "run"

    provider = resolve_provider(os.getenv("AI_PROVIDER"))
    agent_name = os.getenv("DBOS_AGENT_NAME", "chat")

    backend = build_backend()
    approval_store = ApprovalStore.from_env(base_dir=base_dir)
    key_manager = ApprovalKeyManager.from_env(base_dir=base_dir)
    if not args.no_approval and not is_batch:
        key_manager.ensure_unlocked_interactive()
    tool_policy = ToolPolicyRegistry.default()
    memory_db_path = resolve_memory_db_path(
        os.getenv("DBOS_SYSTEM_DATABASE_URL", "sqlite:///dbostest.sqlite")
    )
    init_memory_store(memory_db_path)
    workspace_root = resolve_workspace_root()
    sub_db_path = str(Path(memory_db_path).with_name("subscriptions.sqlite"))
    subscription_registry = SubscriptionRegistry(sub_db_path)
    # Knowledge system: index files and load context
    knowledge_root = workspace_root / "knowledge"
    knowledge_db_path = str(Path(memory_db_path).with_name("knowledge.sqlite"))
    init_knowledge_index(knowledge_db_path)
    reindex_knowledge(knowledge_db_path, knowledge_root)
    ensure_journal_entry(knowledge_root)
    knowledge_context = load_knowledge_context(knowledge_root)

    topics_dir = workspace_root / "topics"
    topic_registry = TopicRegistry(topics_dir)
    toolsets, system_prompt = build_toolsets(
        memory_db_path=memory_db_path,
        subscription_registry=subscription_registry,
        knowledge_db_path=knowledge_db_path,
        knowledge_context=knowledge_context,
        topic_registry=topic_registry,
    )

    def _subscription_processor(msgs: list[ModelMessage]) -> list[ModelMessage]:
        return materialize_subscriptions(
            msgs,
            subscription_registry,
            workspace_root,
            memory_db_path,
        )

    def _topic_processor(msgs: list[ModelMessage]) -> list[ModelMessage]:
        return inject_topic_context(msgs, topic_registry)

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
                _topic_processor,
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

    if is_batch:
        from agent.batch import run_batch

        run_batch(args.task, output_path=args.output, timeout=args.timeout)
        return

    dbos_config: DBOSConfig = {
        "name": os.getenv("DBOS_APP_NAME", "pydantic_dbos_agent"),
        "system_database_url": system_database_url,
    }
    DBOS(config=dbos_config)
    DBOS.launch()
    cli_chat_loop()


if __name__ == "__main__":
    main()
