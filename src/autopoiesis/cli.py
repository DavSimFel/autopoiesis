"""Durable CLI chat entrypoint with DBOS-backed queue execution."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai import Agent

from autopoiesis.agent.config import AgentConfig, load_agent_configs
from autopoiesis.agent.history import build_history_processors
from autopoiesis.agent.model_resolution import resolve_model_from_config, resolve_provider
from autopoiesis.agent.runtime import (
    AgentOptions,
    Runtime,
    build_agent,
    instrument_agent,
    set_runtime,
)
from autopoiesis.agent.validation import validate_slug
from autopoiesis.agent.workspace import AgentPaths, resolve_agent_name, resolve_agent_workspace
from autopoiesis.infra import otel_tracing
from autopoiesis.infra.approval.keys import ApprovalKeyManager
from autopoiesis.infra.approval.policy import ToolPolicyRegistry
from autopoiesis.infra.approval.store import ApprovalStore
from autopoiesis.models import AgentDeps
from autopoiesis.store.history import (
    cleanup_stale_checkpoints,
    init_history_store,
    resolve_history_db_path,
)
from autopoiesis.tools.toolset_builder import LocalBackend, build_backend, prepare_toolset_context

try:
    from dbos import DBOS, DBOSConfig
except ModuleNotFoundError as exc:
    missing_package = exc.name or "unknown package"
    raise SystemExit(
        f"Missing DBOS dependency package `{missing_package}`. Run `uv sync` so "
        "`pydantic-ai-slim[dbos,mcp]` and `dbos` are installed."
    ) from exc


# Module-level registry for loaded agent configs (populated in main() when --config is provided)
_agent_configs: dict[str, AgentConfig] = {}


def get_agent_configs() -> dict[str, AgentConfig]:
    """Return loaded agent configs, or empty dict if none were loaded."""
    return _agent_configs


def _rotate_key(agent_paths: AgentPaths) -> None:
    """Rotate active approval signing key and expire pending envelopes."""
    approval_store = ApprovalStore.from_env(base_dir=agent_paths.root)
    key_manager = ApprovalKeyManager.from_env(base_dir=agent_paths.root)
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
    return parser.parse_args(argv if argv is not None else sys.argv[1:])


def _resolve_startup_config() -> tuple[str, str]:
    """Resolve provider name and DBOS system database URL."""
    provider = resolve_provider(os.getenv("AI_PROVIDER"))
    system_database_url = os.getenv("DBOS_SYSTEM_DATABASE_URL", "sqlite:///dbostest.sqlite")
    return provider, system_database_url


def initialize_runtime(
    agent_paths: AgentPaths,
    agent_name: str,
    *,
    require_approval_unlock: bool,
    agent_config: AgentConfig | None = None,
) -> str:
    """Build runtime dependencies and register the process-wide runtime.

    When *agent_config* is provided it acts as the source of truth for:

    * **model** — ``AgentConfig.model`` is resolved via
      :func:`~autopoiesis.agent.model_resolution.resolve_model_from_config` and
      passed to :func:`~autopoiesis.agent.runtime.build_agent` as
      *model_override*, bypassing the provider-based default.
    * **tools** — ``AgentConfig.tools`` is forwarded to
      :func:`~autopoiesis.tools.toolset_builder.prepare_toolset_context` to
      filter which toolsets are assembled.
    * **system prompt** — when ``AgentConfig.system_prompt`` resolves to an
      existing file under *agent_paths.root* its contents replace the
      auto-composed prompt.
    * **shell tier** — ``AgentConfig.shell_tier`` is stored on
      :class:`~autopoiesis.agent.runtime.Runtime` for downstream enforcement.

    When *agent_config* is ``None`` all defaults are used (backward-compatible
    behaviour).
    """
    provider, system_database_url = _resolve_startup_config()

    # --- Derive per-agent settings from config (when present) ---
    model_override = None
    tool_names: list[str] | None = None
    shell_tier = "review"

    if agent_config is not None:
        model_override = resolve_model_from_config(agent_config.model)
        tool_names = list(agent_config.tools)
        shell_tier = agent_config.shell_tier
        # Use config name for the DBOS agent queue instead of env default.
        agent_name = agent_config.name

    backend: LocalBackend = build_backend()
    approval_store = ApprovalStore.from_env(base_dir=agent_paths.root)
    key_manager = ApprovalKeyManager.from_env(base_dir=agent_paths.root)
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
    ) = prepare_toolset_context(history_db_path, tool_names=tool_names)

    # When a config-specified system prompt file exists, use it instead of the
    # auto-composed one produced by toolset assembly.
    if agent_config is not None:
        prompt_path = agent_paths.root / agent_config.system_prompt
        if prompt_path.is_file():
            system_prompt = prompt_path.read_text(encoding="utf-8")

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
        model_override=model_override,
    )
    instrument_agent(agent)

    init_history_store(history_db_path)
    cleanup_stale_checkpoints(history_db_path)
    set_runtime(
        Runtime(
            agent=agent,
            agent_name=agent_name,
            backend=backend,
            history_db_path=history_db_path,
            knowledge_db_path=knowledge_db_path,
            subscription_registry=subscription_registry,
            approval_store=approval_store,
            key_manager=key_manager,
            tool_policy=tool_policy,
            approval_unlocked=require_approval_unlock,
            shell_tier=shell_tier,
        )
    )
    return system_database_url


def main() -> None:
    """Load config, assemble runtime components, and launch DBOS + CLI chat."""
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(dotenv_path=repo_root / ".env")
    otel_tracing.configure()

    args = parse_cli_args(repo_root)
    agent_name = resolve_agent_name(getattr(args, "agent", None))
    agent_paths = resolve_agent_workspace(agent_name)

    # --- Load multi-agent config if provided ---
    selected_config: AgentConfig | None = None
    config_path_str = getattr(args, "config", None) or os.environ.get("AUTOPOIESIS_AGENTS_CONFIG")
    if config_path_str:
        # Validate agent name early before touching filesystem or network.
        if args.agent:
            validate_slug(args.agent)

        agent_configs = load_agent_configs(Path(config_path_str))
        # Store on a module-level registry for other components to access.
        _agent_configs.update(agent_configs)

        # Select the active agent's config — fail fast with an actionable message
        # if the requested agent name is not present in the config file.
        if agent_configs and agent_name not in agent_configs:
            available = ", ".join(sorted(agent_configs))
            raise SystemExit(
                f"Agent '{agent_name}' not found in config '{config_path_str}'. "
                f"Available agents: {available}. "
                f"Use --agent to select one of them, or omit --config to use defaults."
            )

        selected_config = agent_configs.get(agent_name)

    if args.command == "rotate-key":
        _rotate_key(agent_paths)
        return

    is_batch = args.command == "run"
    is_serve = args.command == "serve"
    try:
        system_database_url = initialize_runtime(
            agent_paths,
            agent_name,
            require_approval_unlock=not args.no_approval and not is_batch and not is_serve,
            agent_config=selected_config,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Failed to initialize runtime: {exc}") from exc

    if is_batch:
        from autopoiesis.agent.batch import run_batch

        run_batch(args.task, output_path=args.output, timeout=args.timeout)
        return

    dbos_config: DBOSConfig = {
        "name": os.getenv("DBOS_APP_NAME", "pydantic_dbos_agent"),
        "system_database_url": system_database_url,
    }
    DBOS(config=dbos_config)
    DBOS.launch()

    if is_serve:
        from autopoiesis.server.cli import run_server

        run_server(host=args.host, port=args.port)
        return

    from autopoiesis.agent.cli import cli_chat_loop

    cli_chat_loop()


if __name__ == "__main__":
    main()
