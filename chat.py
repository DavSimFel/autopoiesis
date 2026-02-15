"""Durable CLI chat with DBOS-backed priority queue execution.

All work — including interactive chat — flows through the DBOS priority queue.
When a stream handle is registered for a work item, the worker streams tokens
in real time. Durability comes from the final output, not the stream.
"""

import asyncio
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

from models import WorkItem, WorkItemInput, WorkItemOutput, WorkItemPriority, WorkItemType
from streaming import PrintStreamHandle, register_stream, take_stream
from work_queue import work_queue

# ---------------------------------------------------------------------------
# Agent deps
# ---------------------------------------------------------------------------


@dataclass
class AgentDeps:
    """Runtime dependencies injected into agent turns.

    ``backend`` is an explicit field so ``AgentDeps`` structurally matches the
    console toolset dependency protocol used by ``pydantic-ai-backend``.
    """

    backend: LocalBackend


# ---------------------------------------------------------------------------
# Runtime state — set once in main(), read by queue workers
# ---------------------------------------------------------------------------


@dataclass
class _Runtime:
    """Holds initialised agent + backend for the lifetime of the process."""

    agent: Agent[AgentDeps, str]
    backend: LocalBackend


_runtime: _Runtime | None = None


def _set_runtime(agent: Agent[AgentDeps, str], backend: LocalBackend) -> None:
    global _runtime
    _runtime = _Runtime(agent=agent, backend=backend)


def _get_runtime() -> _Runtime:
    if _runtime is None:
        raise RuntimeError("Runtime not initialised. Start the app via main().")
    return _runtime


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------


def required_env(name: str) -> str:
    """Return env var value or exit with a clear startup error.

    Failing fast with ``SystemExit`` (not ``KeyError``) ensures missing
    required configuration surfaces before any conversation begins.
    """
    value = os.getenv(name)
    if value:
        return value
    raise SystemExit(f"Missing required environment variable: {name}")


def resolve_workspace_root() -> Path:
    """Resolve and create the agent workspace root directory.

    Relative ``AGENT_WORKSPACE_ROOT`` values are resolved from this file's
    directory (not CWD) for consistent behaviour across local runs,
    containers, and process launch contexts.
    """
    raw_root = os.getenv("AGENT_WORKSPACE_ROOT", "data/agent-workspace")
    path = Path(raw_root)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_backend() -> LocalBackend:
    """Create the local filesystem backend with shell execution disabled.

    The backend always uses the resolved workspace root and ``enable_execute``
    stays ``False`` to keep tool access scoped to file operations only.
    """
    return LocalBackend(root_dir=resolve_workspace_root(), enable_execute=False)


def validate_console_deps_contract() -> None:
    """Fail fast if console toolset structural assumptions stop holding.

    This guard protects the ``AgentDeps`` → console toolset contract by
    checking both the ``backend`` annotation and required ``LocalBackend``
    methods at startup, before any agent turns execute.
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

    ``create_console_toolset`` is typed for a protocol dependency type; the
    cast is intentional because ``AgentDeps`` satisfies that protocol
    structurally via ``backend: LocalBackend``.
    """
    validate_console_deps_contract()
    toolset = create_console_toolset(include_execute=False, require_write_approval=True)
    return [toolset]


def build_agent(
    provider: str, agent_name: str, toolsets: list[AbstractToolset[AgentDeps]]
) -> Agent[AgentDeps, str]:
    """Create the configured agent from explicit provider/name/toolset inputs.

    Provider selection is passed in by ``main()`` rather than read here,
    keeping this function a focused factory for ``anthropic`` and
    ``openrouter`` variants.
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


# ---------------------------------------------------------------------------
# Queue worker — DBOS workflow + step
# ---------------------------------------------------------------------------


def _deserialize_history(history_json: str | None) -> list[ModelMessage]:
    if not history_json:
        return []
    return ModelMessagesTypeAdapter.validate_json(history_json)


def _serialize_history(messages: list[ModelMessage]) -> str:
    return ModelMessagesTypeAdapter.dump_json(messages).decode()


@DBOS.step()
def run_agent_step(work_item_dict: dict[str, Any]) -> dict[str, Any]:
    """Checkpoint-able agent execution step.

    If a stream handle is registered for this work item, uses
    ``agent.run_stream()`` for real-time token output. Otherwise falls
    back to ``agent.run_sync()``. Either way, returns the durable output.
    """
    rt = _get_runtime()
    item = WorkItem.model_validate(work_item_dict)
    history = _deserialize_history(item.input.message_history_json)
    deps = AgentDeps(backend=rt.backend)

    stream_handle = take_stream(item.id)

    if stream_handle is not None:
        # Streaming path — real-time output to the handle.
        # TODO: replace asyncio.run() with async-native step when moving beyond CLI.
        # asyncio.run() creates a new event loop; breaks if called from an existing one
        # (e.g., inside an async web framework).

        async def _stream() -> WorkItemOutput:
            async with rt.agent.run_stream(
                item.input.prompt,
                deps=deps,
                message_history=history,
            ) as stream:
                async for chunk in stream.stream_text(delta=True):
                    stream_handle.write(chunk)
                stream_handle.close()
                result_text: str = await stream.get_output()
                all_msgs = stream.all_messages()
            return WorkItemOutput(
                text=result_text,
                message_history_json=_serialize_history(all_msgs),
            )

        try:
            output = asyncio.run(_stream())
        except Exception:
            stream_handle.close()
            raise
    else:
        # Non-streaming path — background work
        result = rt.agent.run_sync(item.input.prompt, deps=deps, message_history=history)
        output = WorkItemOutput(
            text=result.output,
            message_history_json=_serialize_history(result.all_messages()),
        )

    return output.model_dump()


@DBOS.workflow()
def execute_work_item(work_item_dict: dict[str, Any]) -> dict[str, Any]:
    """Execute any work item from the DBOS queue.

    All work — chat, research, code, review — flows through this single
    workflow. Returns a dict-serialised ``WorkItemOutput``.
    """
    return run_agent_step(work_item_dict)


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------


def enqueue(item: WorkItem) -> str:
    """Enqueue a work item and return its id. Fire-and-forget."""
    with SetEnqueueOptions(priority=int(item.priority)):
        work_queue.enqueue(execute_work_item, item.model_dump())
    return item.id


def enqueue_and_wait(item: WorkItem) -> WorkItemOutput:
    """Enqueue a work item and block until complete. Returns structured output."""
    with SetEnqueueOptions(priority=int(item.priority)):
        handle = work_queue.enqueue(execute_work_item, item.model_dump())
    raw = handle.get_result()
    return WorkItemOutput.model_validate(raw)


# ---------------------------------------------------------------------------
# CLI chat loop
# ---------------------------------------------------------------------------


def cli_chat_loop() -> None:
    """Interactive CLI chat — every message goes through the work queue.

    Each user message becomes a WorkItem with CRITICAL priority and a
    PrintStreamHandle for real-time output. Message history flows through
    WorkItemInput/Output for multi-turn continuity.
    """
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
            item = WorkItem(
                type=WorkItemType.CHAT,
                priority=WorkItemPriority.CRITICAL,
                input=WorkItemInput(
                    prompt=user_input,
                    message_history_json=history_json,
                ),
            )

            # Register a stream handle so the worker streams to stdout
            register_stream(item.id, PrintStreamHandle())

            output = enqueue_and_wait(item)
            history_json = output.message_history_json

        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Load config, assemble runtime components, and launch DBOS + CLI chat.

    Startup order is intentional:
    1. load ``.env`` relative to this file
    2. read provider + agent naming from env
    3. build backend → toolsets → agent
    4. store runtime state for queue workers
    5. configure and launch DBOS
    6. enter interactive CLI chat loop (all input via queue)
    """
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

    provider = os.getenv("AI_PROVIDER", "anthropic").lower()
    agent_name = os.getenv("DBOS_AGENT_NAME", "chat")

    backend = build_backend()
    toolsets = build_toolsets()
    agent = build_agent(provider, agent_name, toolsets)
    _set_runtime(agent, backend)

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
