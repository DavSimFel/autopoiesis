"""Durable CLI chat entrypoint with DBOS-backed queue execution."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai import Agent

from agent.history import build_history_processors
from agent.runtime import (
    AgentOptions,
    Runtime,
    build_agent,
    instrument_agent,
    set_runtime,
)
from approval.keys import ApprovalKeyManager
from approval.policy import ToolPolicyRegistry
from approval.store import ApprovalStore
from infra import otel_tracing
from model_resolution import resolve_provider
from models import AgentDeps
from store.history import (
    cleanup_stale_checkpoints,
    init_history_store,
    resolve_history_db_path,
)
from toolset_builder import LocalBackend, build_backend, prepare_toolset_context

try:
    from dbos import DBOS, DBOSConfig
except ModuleNotFoundError as exc:
    missing_package = exc.name or "unknown package"
    raise SystemExit(
        f"Missing DBOS dependency package `{missing_package}`. Run `uv sync` so "
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


def _resolve_startup_config() -> tuple[str, str, str]:
    """Resolve provider/agent names and DBOS system database URL."""
    provider = resolve_provider(os.getenv("AI_PROVIDER"))
    agent_name = os.getenv("DBOS_AGENT_NAME", "chat")
    system_database_url = os.getenv(
        "DBOS_SYSTEM_DATABASE_URL",
        "sqlite:///dbostest.sqlite",
    )
    return provider, agent_name, system_database_url


def _initialize_runtime(
    base_dir: Path,
    *,
    require_approval_unlock: bool,
) -> str:
    """Build runtime dependencies and register the process-wide runtime."""
    provider, agent_name, system_database_url = _resolve_startup_config()

    backend: LocalBackend = build_backend()
    approval_store = ApprovalStore.from_env(base_dir=base_dir)
    key_manager = ApprovalKeyManager.from_env(base_dir=base_dir)
    if require_approval_unlock:
        key_manager.ensure_unlocked_interactive()
    tool_policy = ToolPolicyRegistry.default()
    history_db_path = resolve_history_db_path(system_database_url)
    (
        workspace_root,
        knowledge_db_path,
        subscription_registry,
        topic_registry,
        toolsets,
        system_prompt,
    ) = prepare_toolset_context(history_db_path)
    history_processors = build_history_processors(
        subscription_registry=subscription_registry,
        workspace_root=workspace_root,
        knowledge_db_path=knowledge_db_path,
        topic_registry=topic_registry,
    )

    agent: Agent[AgentDeps, str] = build_agent(
        provider,
        agent_name,
        toolsets,
        system_prompt,
        options=AgentOptions(history_processors=history_processors),
    )
    instrument_agent(agent)

    init_history_store(history_db_path)
    cleanup_stale_checkpoints(history_db_path)
    set_runtime(
        Runtime(
            agent=agent,
            backend=backend,
            history_db_path=history_db_path,
            knowledge_db_path=knowledge_db_path,
            subscription_registry=subscription_registry,
            approval_store=approval_store,
            key_manager=key_manager,
            tool_policy=tool_policy,
        )
    )
    return system_database_url


def main() -> None:
    """Load config, assemble runtime components, and launch DBOS + CLI chat."""
    base_dir = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=base_dir / ".env")
    otel_tracing.configure()

    args = parse_cli_args(base_dir)
    if args.command == "rotate-key":
        _rotate_key(base_dir)
        return

    is_batch = args.command == "run"
    is_serve = args.command == "serve"
    try:
        system_database_url = _initialize_runtime(
            base_dir,
            require_approval_unlock=not args.no_approval and not is_batch and not is_serve,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Failed to initialize runtime: {exc}") from exc

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

    if is_serve:
        from server.cli import run_server

        run_server(host=args.host, port=args.port)
        return

    from agent.cli import cli_chat_loop

    cli_chat_loop()


if __name__ == "__main__":
    main()
