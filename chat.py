"""Durable interactive CLI chat with DBOS persistence and provider switching.

Run this module as the project entrypoint to load repo-local `.env` settings,
build the agent/backend/toolset stack, launch DBOS, and start an interactive
CLI session. `AI_PROVIDER` selects `anthropic` or `openrouter` at startup.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai import AbstractToolset, Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

try:
    from dbos import DBOS, DBOSConfig
    from pydantic_ai.durable_exec.dbos import DBOSAgent
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing DBOS dependencies. Run `uv sync` so "
        "`pydantic-ai-slim[dbos,mcp]` and `dbos` are installed."
    ) from exc

try:
    from pydantic_ai_backends import LocalBackend, create_console_toolset
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing backend dependency. Run `uv sync` so `pydantic-ai-backend==0.1.6` is installed."
    ) from exc


@dataclass
class AgentDeps:
    """Runtime dependencies injected into agent turns.

    `backend` is kept as an explicit field so `AgentDeps` structurally matches
    the console toolset dependency protocol used by `pydantic-ai-backend`.
    """

    backend: LocalBackend


def required_env(name: str) -> str:
    """Return env var value or exit with a clear startup error.

    Failing fast with `SystemExit` (not `KeyError`) ensures missing required
    configuration is surfaced before any interactive conversation begins.
    """

    value = os.getenv(name)
    if value:
        return value
    raise SystemExit(f"Missing required environment variable: {name}")


def resolve_workspace_root() -> Path:
    """Resolve and create the agent workspace root directory.

    Relative `AGENT_WORKSPACE_ROOT` values are resolved from this file's
    directory (not the current working directory) for consistent behavior
    across local runs, containers, and process launch contexts.
    """

    raw_root = os.getenv("AGENT_WORKSPACE_ROOT", "data/agent-workspace")
    path = Path(raw_root)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_backend() -> LocalBackend:
    """Create the local filesystem backend with shell execution disabled.

    The backend always uses the resolved workspace root and `enable_execute`
    stays `False` to keep tool access scoped to file operations only.
    """

    return LocalBackend(root_dir=resolve_workspace_root(), enable_execute=False)


def validate_console_deps_contract() -> None:
    """Fail fast if console toolset structural assumptions stop holding.

    This guard protects the intentional cast in `build_toolsets()` by checking
    both `AgentDeps.backend` typing and the required `LocalBackend` methods.
    """

    backend_annotation = AgentDeps.__annotations__.get("backend")
    if backend_annotation is not LocalBackend:
        raise SystemExit(
            "AgentDeps.backend must be typed as LocalBackend to satisfy "
            "console toolset dependency expectations."
        )

    required_backend_methods = (
        "ls_info",
        "read",
        "write",
        "edit",
        "glob_info",
        "grep_raw",
    )
    missing = [
        name for name in required_backend_methods if not callable(getattr(LocalBackend, name, None))
    ]
    if missing:
        raise SystemExit(
            "LocalBackend is missing required console backend methods: "
            + ", ".join(sorted(missing))
        )


def build_toolsets() -> list[AbstractToolset[AgentDeps]]:
    """Build console toolsets with execute disabled and write approval enabled.

    `create_console_toolset` is typed for a protocol dependency type; we cast
    intentionally because `AgentDeps` satisfies that protocol structurally.
    """

    validate_console_deps_contract()
    toolset = create_console_toolset(include_execute=False, require_write_approval=True)
    return [toolset]


def build_agent(
    provider: str, agent_name: str, toolsets: list[AbstractToolset[AgentDeps]]
) -> Agent[AgentDeps, str]:
    """Create the configured agent from explicit provider/name/toolset inputs.

    Provider selection is passed in by `main()` rather than read here, keeping
    this function a focused factory for `anthropic` and `openrouter` variants.
    """

    if provider == "anthropic":
        required_env("ANTHROPIC_API_KEY")
        return Agent(
            os.getenv("ANTHROPIC_MODEL", "anthropic:claude-3-5-sonnet-latest"),
            deps_type=AgentDeps,
            toolsets=toolsets,
            name=agent_name,
        )
    if provider == "openrouter":
        model = OpenAIChatModel(
            os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
            provider=OpenAIProvider(
                base_url="https://openrouter.ai/api/v1",
                api_key=required_env("OPENROUTER_API_KEY"),
            ),
        )
        return Agent(model, deps_type=AgentDeps, toolsets=toolsets, name=agent_name)
    raise SystemExit("Unsupported AI_PROVIDER. Use 'openrouter' or 'anthropic'.")


def main() -> None:
    """Load config, assemble runtime components, then launch durable CLI chat.

    The startup order is intentional: load `.env`, read provider/agent naming,
    build backend/toolsets/agent, initialize DBOS, launch DBOS, then attach
    runtime deps for interactive execution.
    """

    load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

    provider = os.getenv("AI_PROVIDER", "anthropic").lower()
    agent_name = os.getenv("DBOS_AGENT_NAME", "chat")

    backend = build_backend()
    toolsets = build_toolsets()
    agent = build_agent(provider, agent_name, toolsets)

    dbos_config: DBOSConfig = {
        "name": os.getenv("DBOS_APP_NAME", "pydantic_dbos_agent"),
        "system_database_url": os.getenv(
            "DBOS_SYSTEM_DATABASE_URL",
            "sqlite:///dbostest.sqlite",
        ),
    }
    DBOS(config=dbos_config)

    dbos_agent = DBOSAgent(agent, name=agent_name)

    DBOS.launch()
    dbos_agent.to_cli_sync(deps=AgentDeps(backend=backend))


if __name__ == "__main__":
    main()
