"""Durable interactive CLI chat with DBOS-backed priority queue execution.

All work — including interactive chat — flows through the DBOS priority queue.
Interactive chat uses agent.run_stream() with message_history for multi-turn
conversation and streaming output.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic_ai import AbstractToolset, Agent
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

try:
    from dbos import DBOS, DBOSConfig, SetEnqueueOptions
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

from models import TaskPayload, TaskPriority, TaskType
from work_queue import work_queue


@dataclass
class AgentDeps:
    """Runtime dependencies injected into agent turns."""

    backend: LocalBackend


_runtime_agent: Agent[AgentDeps, str] | None = None
_runtime_backend: LocalBackend | None = None


def required_env(name: str) -> str:
    """Return env var value or exit with a clear startup error."""

    value = os.getenv(name)
    if value:
        return value
    raise SystemExit(f"Missing required environment variable: {name}")


def resolve_workspace_root() -> Path:
    """Resolve and create the agent workspace root directory."""

    raw_root = os.getenv("AGENT_WORKSPACE_ROOT", "data/agent-workspace")
    path = Path(raw_root)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_backend() -> LocalBackend:
    """Create the local filesystem backend with shell execution disabled."""

    return LocalBackend(root_dir=resolve_workspace_root(), enable_execute=False)


def validate_console_deps_contract() -> None:
    """Fail fast if console toolset structural assumptions stop holding."""

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
    """Build console toolsets with execute disabled and write approval enabled."""

    validate_console_deps_contract()
    toolset = create_console_toolset(include_execute=False, require_write_approval=True)
    return [toolset]


def build_agent(
    provider: str, agent_name: str, toolsets: list[AbstractToolset[AgentDeps]]
) -> Agent[AgentDeps, str]:
    """Create the configured agent from explicit provider/name/toolset inputs."""

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


def set_runtime_state(agent: Agent[AgentDeps, str], backend: LocalBackend) -> None:
    """Store runtime references used by DBOS background task handlers."""

    global _runtime_agent, _runtime_backend
    _runtime_agent = agent
    _runtime_backend = backend


def get_runtime_agent() -> Agent[AgentDeps, str]:
    """Return initialized agent runtime state or fail fast for invalid startup."""

    if _runtime_agent is None:
        raise RuntimeError("Runtime agent is not initialized. Start the app via main().")
    return _runtime_agent


def get_runtime_backend() -> LocalBackend:
    """Return initialized backend runtime state or fail fast for invalid startup."""

    if _runtime_backend is None:
        raise RuntimeError("Runtime backend is not initialized. Start the app via main().")
    return _runtime_backend


@DBOS.step()
def run_agent_step(prompt: str, message_history_json: str | None = None) -> str:
    """Checkpoint-able agent execution step.

    Accepts optional serialized message_history for multi-turn conversations.
    Returns JSON with 'output' and 'messages' for history continuity.
    """

    import json

    agent = get_runtime_agent()
    backend = get_runtime_backend()

    history: list[ModelMessage] = []
    if message_history_json:
        history = ModelMessagesTypeAdapter.validate_json(message_history_json)

    result = agent.run_sync(
        prompt,
        deps=AgentDeps(backend=backend),
        message_history=history,
    )

    return json.dumps(
        {
            "output": result.output,
            "messages": ModelMessagesTypeAdapter.dump_json(result.all_messages()).decode(),
        }
    )


@DBOS.workflow()
def execute_task(payload_dict: dict[str, Any]) -> str:
    """Execute any task from the DBOS work queue.

    All work — chat, research, code, review — flows through this single
    workflow. Chat tasks include message_history in context for multi-turn.
    Returns JSON with output and updated message history.
    """

    payload = TaskPayload.model_validate(payload_dict)
    history_json = payload.context.get("message_history_json")
    return run_agent_step(payload.prompt, history_json)


def enqueue_task(task_type: TaskType, prompt: str, **kwargs: Any) -> str:
    """Enqueue work and return the generated task id."""

    payload = TaskPayload(type=task_type, prompt=prompt, **kwargs)
    with SetEnqueueOptions(priority=int(payload.priority)):
        work_queue.enqueue(execute_task, payload.model_dump())
    return payload.id


def enqueue_task_and_wait(task_type: TaskType, prompt: str, **kwargs: Any) -> str:
    """Enqueue work and block until complete. Returns raw result JSON."""

    payload = TaskPayload(type=task_type, prompt=prompt, **kwargs)
    with SetEnqueueOptions(priority=int(payload.priority)):
        handle = work_queue.enqueue(execute_task, payload.model_dump())
    return handle.get_result()


def cli_chat_loop() -> None:
    """Interactive CLI chat loop — every message enqueues through the work queue.

    Chat messages enter as TaskType.CHAT with CRITICAL priority.
    Message history is passed via task context for multi-turn continuity.
    Type 'exit' or Ctrl+C to quit.
    """

    import json

    history_json: str | None = None
    print("Autopoiesis CLI Chat (type 'exit' to quit)")
    print("---")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Goodbye.")
            break

        try:
            context: dict[str, Any] = {}
            if history_json:
                context["message_history_json"] = history_json

            result_json = enqueue_task_and_wait(
                TaskType.CHAT,
                user_input,
                priority=TaskPriority.CRITICAL,
                context=context,
            )

            result = json.loads(result_json)
            print(result["output"])
            history_json = result["messages"]

        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)


def main() -> None:
    """Load config, assemble runtime components, and launch DBOS + CLI chat."""

    load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

    provider = os.getenv("AI_PROVIDER", "anthropic").lower()
    agent_name = os.getenv("DBOS_AGENT_NAME", "chat")

    backend = build_backend()
    toolsets = build_toolsets()
    agent = build_agent(provider, agent_name, toolsets)
    set_runtime_state(agent, backend)

    dbos_config: DBOSConfig = {
        "name": os.getenv("DBOS_APP_NAME", "pydantic_dbos_agent"),
        "system_database_url": os.getenv(
            "DBOS_SYSTEM_DATABASE_URL",
            "sqlite:///dbostest.sqlite",
        ),
    }
    DBOS(config=dbos_config)

    DBOS.launch()
    cli_chat_loop()


if __name__ == "__main__":
    main()
