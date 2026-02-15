import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic_ai import AbstractToolset, Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from dotenv import load_dotenv


try:
    from dbos import DBOS, DBOSConfig
    from pydantic_ai.durable_exec.dbos import DBOSAgent
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing DBOS dependencies. Run `uv sync` so `pydantic-ai-slim[dbos,mcp]` and `dbos` are installed."
    ) from exc

try:
    from pydantic_ai_backends import LocalBackend, create_console_toolset
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing backend dependency. Run `uv sync` so `pydantic-ai-backend==0.1.6` is installed."
    ) from exc


@dataclass
class AgentDeps:
    backend: LocalBackend


def required_env(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    raise SystemExit(f"Missing required environment variable: {name}")


def resolve_workspace_root() -> Path:
    raw_root = os.getenv("AGENT_WORKSPACE_ROOT", "data/agent-workspace")
    path = Path(raw_root)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_backend() -> LocalBackend:
    return LocalBackend(root_dir=resolve_workspace_root(), enable_execute=False)


def validate_console_deps_contract() -> None:
    backend_annotation = AgentDeps.__annotations__.get("backend")
    if backend_annotation is not LocalBackend:
        raise SystemExit(
            "AgentDeps.backend must be typed as LocalBackend to satisfy console toolset dependency expectations."
        )

    required_backend_methods = ("ls_info", "read", "write", "edit", "glob_info", "grep_raw")
    missing = [name for name in required_backend_methods if not callable(getattr(LocalBackend, name, None))]
    if missing:
        raise SystemExit(
            "LocalBackend is missing required console backend methods: " + ", ".join(sorted(missing))
        )


def build_toolsets() -> list[AbstractToolset[AgentDeps]]:
    validate_console_deps_contract()
    toolset = create_console_toolset(include_execute=False, require_write_approval=True)
    # `create_console_toolset` returns FunctionToolset[ConsoleDeps]. This cast is intentional:
    # AgentDeps satisfies that protocol structurally via `backend: LocalBackend`.
    return cast(list[AbstractToolset[AgentDeps]], [toolset])


def build_agent(
    provider: str, agent_name: str, toolsets: list[AbstractToolset[AgentDeps]]
) -> Agent[AgentDeps, str]:
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
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

    provider = os.getenv("AI_PROVIDER", "anthropic").lower()
    agent_name = os.getenv("DBOS_AGENT_NAME", "chat")

    backend = build_backend()
    toolsets = build_toolsets()
    agent = build_agent(provider, agent_name, toolsets)

    dbos_config: DBOSConfig = {
        "name": os.getenv("DBOS_APP_NAME", "pydantic_dbos_agent"),
        "system_database_url": os.getenv("DBOS_SYSTEM_DATABASE_URL", "sqlite:///dbostest.sqlite"),
    }
    DBOS(config=dbos_config)

    dbos_agent = DBOSAgent(agent, name=agent_name)

    DBOS.launch()
    dbos_agent.to_cli_sync(deps=AgentDeps(backend=backend))


if __name__ == "__main__":
    main()
