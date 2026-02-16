"""Durable CLI chat with DBOS-backed priority queue execution.

All work — including interactive chat — flows through the DBOS priority queue.
When a stream handle is registered for a work item, the worker streams tokens
in real time. Durability comes from the final output, not the stream.

Tools that require write approval produce ``DeferredToolRequests``. The caller
(e.g. CLI chat loop) gathers human approval and re-enqueues with the decisions.
"""

import asyncio
import json
import os
import sys
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast, get_type_hints

from dotenv import load_dotenv
from pydantic_ai import AbstractToolset, Agent, DeferredToolRequests
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import DeferredToolResults, ToolDenied

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

from history_store import (
    cleanup_stale_checkpoints,
    clear_checkpoint,
    init_history_store,
    load_checkpoint,
    resolve_history_db_path,
    save_checkpoint,
)
from models import (
    AgentDeps,
    WorkItem,
    WorkItemInput,
    WorkItemOutput,
    WorkItemPriority,
    WorkItemType,
)
from skills import SkillDirectory, create_skills_toolset
from streaming import PrintStreamHandle, register_stream, take_stream
from work_queue import work_queue

# The union output type for agent runs — str for normal responses,
# DeferredToolRequests when tools need approval before execution.
AgentOutput = str | DeferredToolRequests

# Maximum characters to display for a tool argument value in the approval UI.
_APPROVAL_ARG_DISPLAY_MAX = 200

# ---------------------------------------------------------------------------
# Runtime state — set once in main(), read by queue workers
# ---------------------------------------------------------------------------


@dataclass
class _Runtime:
    """Holds initialised agent + backend for the lifetime of the process."""

    agent: Agent[AgentDeps, str]
    backend: LocalBackend
    history_db_path: str


@dataclass(frozen=True)
class _CheckpointContext:
    """Per-run checkpoint metadata used by history processors."""

    db_path: str
    work_item_id: str


_runtime: _Runtime | None = None
_active_checkpoint_context: ContextVar[_CheckpointContext | None] = ContextVar(
    "active_checkpoint_context",
    default=None,
)


def _set_runtime(agent: Agent[AgentDeps, str], backend: LocalBackend, history_db_path: str) -> None:
    global _runtime
    _runtime = _Runtime(agent=agent, backend=backend, history_db_path=history_db_path)


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
    try:
        backend_annotation = get_type_hints(AgentDeps).get("backend")
    except (NameError, TypeError) as exc:
        raise SystemExit(
            "Failed to resolve AgentDeps type annotations for console toolset validation."
        ) from exc
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


def _resolve_shipped_skills_dir() -> Path:
    """Resolve shipped skills, defaulting to ``skills/`` beside ``chat.py``."""
    raw = os.getenv("SKILLS_DIR", "skills")
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def _resolve_custom_skills_dir() -> Path:
    """Resolve custom skills, defaulting to ``skills/`` inside the workspace."""
    raw = os.getenv("CUSTOM_SKILLS_DIR", "skills")
    path = Path(raw)
    if not path.is_absolute():
        path = resolve_workspace_root() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_skill_directories() -> list[SkillDirectory]:
    """Build skill directories in precedence order: shipped, then custom."""
    shipped_dir = _resolve_shipped_skills_dir()
    custom_dir = _resolve_custom_skills_dir()
    if shipped_dir.resolve() == custom_dir.resolve():
        return [SkillDirectory(path=shipped_dir)]
    return [SkillDirectory(path=shipped_dir), SkillDirectory(path=custom_dir)]


_CONSOLE_INSTRUCTIONS = (
    "You have filesystem tools for reading, writing, and editing files "
    "in the workspace. Write and edit operations require user approval. "
    "Shell execution is disabled."
)


def build_toolsets() -> tuple[list[AbstractToolset[AgentDeps]], list[str]]:
    """Build all toolsets and collect their system prompt instructions.

    Returns ``(toolsets, instructions)`` — each module contributes both a
    toolset and an optional instructions string. Empty instructions are
    filtered out so they don't bloat the system prompt.
    """
    validate_console_deps_contract()
    console = create_console_toolset(include_execute=False, require_write_approval=True)
    skills_toolset, skills_instr = create_skills_toolset(_build_skill_directories())

    toolsets: list[AbstractToolset[AgentDeps]] = [console, skills_toolset]
    instructions = [i for i in [_CONSOLE_INSTRUCTIONS, skills_instr] if i]
    return toolsets, instructions


def build_agent(
    provider: str,
    agent_name: str,
    toolsets: list[AbstractToolset[AgentDeps]],
    instructions: list[str],
) -> Agent[AgentDeps, str]:
    """Create the configured agent from explicit provider/name/toolset/instructions.

    Each module contributes toolsets and instructions. The ``instructions``
    list is passed directly to PydanticAI's ``instructions`` parameter —
    PydanticAI composes them into the system prompt and re-sends them on
    every turn (even with ``message_history``).
    """
    all_instructions: list[str] = [
        "You are a helpful coding assistant with filesystem and skill tools.",
        *instructions,
    ]
    if provider == "anthropic":
        required_env("ANTHROPIC_API_KEY")
        return Agent(
            os.getenv("ANTHROPIC_MODEL", "anthropic:claude-3-5-sonnet-latest"),
            deps_type=AgentDeps,
            toolsets=toolsets,
            instructions=all_instructions,
            history_processors=[_checkpoint_history_processor],
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
        return Agent(
            model,
            deps_type=AgentDeps,
            toolsets=toolsets,
            instructions=all_instructions,
            history_processors=[_checkpoint_history_processor],
            name=agent_name,
        )
    raise SystemExit("Unsupported AI_PROVIDER. Use 'openrouter' or 'anthropic'.")


# ---------------------------------------------------------------------------
# Deferred tool serialization
# ---------------------------------------------------------------------------


def _serialize_deferred_requests(requests: DeferredToolRequests) -> str:
    """Serialize DeferredToolRequests to JSON for transport through the queue.

    Extracts the essential fields (tool_call_id, tool_name, args) from each
    approval request so the caller can present them to the user.
    """
    data = [
        {
            "tool_call_id": call.tool_call_id,
            "tool_name": call.tool_name,
            "args": call.args,
        }
        for call in requests.approvals
    ]
    return json.dumps(data)


def _deserialize_deferred_results(results_json: str) -> DeferredToolResults:
    """Deserialize approval decisions from JSON back to DeferredToolResults.

    Expected format: list of {"tool_call_id": str, "approved": bool,
    "denial_message": str | None}.
    """
    data: list[dict[str, Any]] = json.loads(results_json)
    results = DeferredToolResults()
    for entry in data:
        tool_call_id = entry["tool_call_id"]
        if entry["approved"]:
            results.approvals[tool_call_id] = True
        else:
            message = entry.get("denial_message", "User denied this tool call.")
            results.approvals[tool_call_id] = ToolDenied(message)
    return results


# ---------------------------------------------------------------------------
# Queue worker — DBOS workflow + step
# ---------------------------------------------------------------------------


def _deserialize_history(history_json: str | None) -> list[ModelMessage]:
    if not history_json:
        return []
    return ModelMessagesTypeAdapter.validate_json(history_json)


def _serialize_history(messages: list[ModelMessage]) -> str:
    return ModelMessagesTypeAdapter.dump_json(messages).decode()


def _count_history_rounds(messages: list[ModelMessage]) -> int:
    """Count completed model rounds from serialized message history."""
    model_responses = sum(1 for message in messages if isinstance(message, ModelResponse))
    return model_responses if model_responses > 0 else len(messages)


def _checkpoint_history_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Persist an in-flight checkpoint whenever the active work item updates history."""
    checkpoint = _active_checkpoint_context.get()
    if checkpoint is None:
        return messages
    save_checkpoint(
        db_path=checkpoint.db_path,
        work_item_id=checkpoint.work_item_id,
        history_json=_serialize_history(messages),
        round_count=_count_history_rounds(messages),
    )
    return messages


@DBOS.step()
def run_agent_step(work_item_dict: dict[str, Any]) -> dict[str, Any]:
    """Checkpoint-able agent execution step.

    Handles three scenarios:
    1. Streaming with stream handle → ``agent.run_stream()`` with real-time output
    2. Non-streaming → ``agent.run_sync()``
    3. Resuming after deferred tool approval → passes ``deferred_tool_results``

    In all cases, passes ``output_type=[str, DeferredToolRequests]`` so the
    agent can return either a text response or a deferred tool approval request.
    """
    rt = _get_runtime()
    item = WorkItem.model_validate(work_item_dict)
    recovered_history_json = load_checkpoint(rt.history_db_path, item.id)
    history_json = recovered_history_json or item.input.message_history_json
    history = _deserialize_history(history_json)
    deps = AgentDeps(backend=rt.backend)

    # Reconstruct deferred tool results if this is a resumption
    deferred_results: DeferredToolResults | None = None
    if item.input.deferred_tool_results_json:
        deferred_results = _deserialize_deferred_results(item.input.deferred_tool_results_json)

    # For resumptions after tool approval, prompt is None — use empty string
    # for the API call since the original prompt is already in message_history.
    prompt = item.input.prompt or ""

    stream_handle = take_stream(item.id)
    output_type: list[type[AgentOutput]] = [str, DeferredToolRequests]
    checkpoint_token: Token[_CheckpointContext | None] = _active_checkpoint_context.set(
        _CheckpointContext(db_path=rt.history_db_path, work_item_id=item.id)
    )

    try:
        if stream_handle is not None:
            # Streaming path — real-time output to the handle.
            # TODO: replace asyncio.run() with async-native step when moving beyond CLI.
            # asyncio.run() creates a new event loop; breaks if called from an existing one
            # (e.g., inside an async web framework).

            async def _stream() -> WorkItemOutput:
                async with rt.agent.run_stream(
                    prompt,
                    deps=deps,
                    message_history=history,
                    output_type=output_type,
                    deferred_tool_results=deferred_results,
                ) as stream:
                    async for chunk in stream.stream_text(delta=True):
                        stream_handle.write(chunk)
                    stream_handle.close()
                    result_output: AgentOutput = await stream.get_output()
                    all_msgs = stream.all_messages()

                if isinstance(result_output, DeferredToolRequests):
                    return WorkItemOutput(
                        deferred_tool_requests_json=_serialize_deferred_requests(result_output),
                        message_history_json=_serialize_history(all_msgs),
                    )
                return WorkItemOutput(
                    text=result_output,
                    message_history_json=_serialize_history(all_msgs),
                )

            try:
                output = asyncio.run(_stream())
            except Exception:
                stream_handle.close()
                raise
        else:
            # Non-streaming path — background work
            result = rt.agent.run_sync(
                prompt,
                deps=deps,
                message_history=history,
                output_type=output_type,
                deferred_tool_results=deferred_results,
            )
            if isinstance(result.output, DeferredToolRequests):
                output = WorkItemOutput(
                    deferred_tool_requests_json=_serialize_deferred_requests(result.output),
                    message_history_json=_serialize_history(result.all_messages()),
                )
            else:
                output = WorkItemOutput(
                    text=result.output,
                    message_history_json=_serialize_history(result.all_messages()),
                )
    finally:
        _active_checkpoint_context.reset(checkpoint_token)

    clear_checkpoint(rt.history_db_path, item.id)
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
# CLI approval display
# ---------------------------------------------------------------------------


def _display_approval_requests(requests_json: str) -> list[dict[str, Any]]:
    """Display pending tool approval requests and return the parsed list."""
    requests: list[dict[str, Any]] = json.loads(requests_json)
    print("\n🔒 Tool approval required:")
    for i, req in enumerate(requests, 1):
        tool_name = req["tool_name"]
        args: Any = req["args"]
        print(f"  [{i}] {tool_name}")
        if isinstance(args, dict):
            for arg_name, arg_value in cast(dict[str, object], args).items():
                display = str(arg_value)
                if len(display) > _APPROVAL_ARG_DISPLAY_MAX:
                    display = display[:_APPROVAL_ARG_DISPLAY_MAX] + "..."
                print(f"      {arg_name}: {display}")
        else:
            print(f"      args: {args}")
    return requests


def _gather_approvals(requests: list[dict[str, Any]]) -> str:
    """Prompt the user for approval decisions on each tool call.

    Returns serialized JSON list of approval decisions for
    ``_deserialize_deferred_results``.
    """
    decisions: list[dict[str, Any]] = []
    if len(requests) == 1:
        try:
            answer = input("  Approve? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        approved = answer in ("", "y", "yes")
        decisions.append(
            {
                "tool_call_id": requests[0]["tool_call_id"],
                "approved": approved,
                "denial_message": None if approved else "User denied this action.",
            }
        )
    else:
        try:
            answer = input("  Approve all? [Y/n/pick] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer in ("", "y", "yes"):
            for req in requests:
                decisions.append(
                    {
                        "tool_call_id": req["tool_call_id"],
                        "approved": True,
                        "denial_message": None,
                    }
                )
        elif answer in ("pick", "p"):
            for i, req in enumerate(requests, 1):
                try:
                    choice = input(f"  [{i}] {req['tool_name']} — approve? [Y/n] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    choice = "n"
                approved = choice in ("", "y", "yes")
                decisions.append(
                    {
                        "tool_call_id": req["tool_call_id"],
                        "approved": approved,
                        "denial_message": None if approved else "User denied this action.",
                    }
                )
        else:
            for req in requests:
                decisions.append(
                    {
                        "tool_call_id": req["tool_call_id"],
                        "approved": False,
                        "denial_message": "User denied this action.",
                    }
                )

    return json.dumps(decisions)


# ---------------------------------------------------------------------------
# CLI chat loop
# ---------------------------------------------------------------------------


def cli_chat_loop() -> None:
    """Interactive CLI chat — every message goes through the work queue.

    Each user message becomes a WorkItem with CRITICAL priority and a
    PrintStreamHandle for real-time output. Message history flows through
    WorkItemInput/Output for multi-turn continuity.

    When the agent requests tool approval (e.g. file writes), the loop
    displays the pending actions, gathers user decisions, and re-enqueues
    with the approval results until the agent produces a final text response.
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
            prompt: str | None = user_input
            deferred_results_json: str | None = None

            # Approval loop — keeps re-enqueuing until we get a text response
            while True:
                item = WorkItem(
                    type=WorkItemType.CHAT,
                    priority=WorkItemPriority.CRITICAL,
                    input=WorkItemInput(
                        prompt=prompt,
                        message_history_json=history_json,
                        deferred_tool_results_json=deferred_results_json,
                    ),
                )

                # Register a stream handle so the worker streams to stdout
                register_stream(item.id, PrintStreamHandle())

                output = enqueue_and_wait(item)
                history_json = output.message_history_json

                if output.deferred_tool_requests_json is not None:
                    # Agent wants tool approval — display and gather decisions
                    requests = _display_approval_requests(output.deferred_tool_requests_json)
                    deferred_results_json = _gather_approvals(requests)
                    # Re-enqueue without prompt — context is in message history
                    prompt = None
                    continue

                # Normal text response — done with this turn
                break

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
    toolsets, instructions = build_toolsets()
    agent = build_agent(provider, agent_name, toolsets, instructions)
    system_database_url = os.getenv(
        "DBOS_SYSTEM_DATABASE_URL",
        "sqlite:///dbostest.sqlite",
    )

    dbos_config: DBOSConfig = {
        "name": os.getenv("DBOS_APP_NAME", "pydantic_dbos_agent"),
        "system_database_url": system_database_url,
    }
    history_db_path = resolve_history_db_path(system_database_url)
    init_history_store(history_db_path)
    cleanup_stale_checkpoints(history_db_path)
    _set_runtime(agent, backend, history_db_path)
    DBOS(config=dbos_config)

    DBOS.launch()
    cli_chat_loop()


if __name__ == "__main__":
    main()
