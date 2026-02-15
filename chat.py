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
from uuid import uuid4

from dotenv import load_dotenv
from pydantic_ai import AbstractToolset, Agent, DeferredToolRequests
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import DeferredToolResults, ToolDenied

from approval_keys import ApprovalKeyManager
from approval_policy import ToolPolicyRegistry
from approval_store import ApprovalStore
from approval_types import (
    ApprovalScope,
    ApprovalVerificationError,
    DeferredToolCall,
    SignedDecision,
)

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

# ---------------------------------------------------------------------------
# Runtime state — set once in main(), read by queue workers
# ---------------------------------------------------------------------------


@dataclass
class _Runtime:
    """Holds initialised agent + backend for the lifetime of the process."""

    agent: Agent[AgentDeps, str]
    backend: LocalBackend
    history_db_path: str
    approval_store: ApprovalStore
    key_manager: ApprovalKeyManager
    tool_policy: ToolPolicyRegistry


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


def _set_runtime(
    agent: Agent[AgentDeps, str],
    backend: LocalBackend,
    history_db_path: str,
    approval_store: ApprovalStore,
    key_manager: ApprovalKeyManager,
    tool_policy: ToolPolicyRegistry,
) -> None:
    global _runtime
    _runtime = _Runtime(
        agent=agent,
        backend=backend,
        history_db_path=history_db_path,
        approval_store=approval_store,
        key_manager=key_manager,
        tool_policy=tool_policy,
    )


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


def _build_approval_scope(
    approval_context_id: str, backend: LocalBackend, agent_name: str
) -> ApprovalScope:
    return ApprovalScope(
        work_item_id=approval_context_id,
        workspace_root=str(Path(backend.root_dir).resolve()),
        agent_name=agent_name,
    )


def _serialize_deferred_requests(
    requests: DeferredToolRequests,
    *,
    scope: ApprovalScope,
    approval_store: ApprovalStore,
    key_manager: ApprovalKeyManager,
    tool_policy: ToolPolicyRegistry,
) -> str:
    """Serialize DeferredToolRequests to JSON for transport through the queue.

    Extracts the essential fields (tool_call_id, tool_name, args) from each
    approval request so the caller can present them to the user.
    """
    data: list[DeferredToolCall] = [
        {
            "tool_call_id": call.tool_call_id,
            "tool_name": call.tool_name,
            "args": call.args,
        }
        for call in requests.approvals
    ]
    tool_policy.validate_deferred_calls(data)
    nonce, plan_hash = approval_store.create_envelope(
        scope=scope,
        tool_calls=data,
        key_id=key_manager.current_key_id(),
    )
    return json.dumps(
        {"nonce": nonce, "plan_hash_prefix": plan_hash[:8], "requests": data},
        ensure_ascii=True,
        allow_nan=False,
    )


def _deserialize_deferred_results(
    results_json: str,
    *,
    scope: ApprovalScope,
    approval_store: ApprovalStore,
    key_manager: ApprovalKeyManager,
) -> DeferredToolResults:
    """Deserialize approval decisions from JSON back to DeferredToolResults.

    Expected format: list of {"tool_call_id": str, "approved": bool,
    "denial_message": str | None}.
    """
    data = approval_store.verify_and_consume(
        submission_json=results_json,
        live_scope=scope,
        key_manager=key_manager,
    )
    results = DeferredToolResults()
    for entry in data:
        tool_call_id = entry["tool_call_id"]
        if entry["approved"]:
            results.approvals[tool_call_id] = True
        else:
            denial_message = entry.get("denial_message")
            message = (
                denial_message
                if isinstance(denial_message, str) and denial_message
                else "User denied this tool call."
            )
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
    agent_name = rt.agent.name or os.getenv("DBOS_AGENT_NAME", "chat")
    approval_context_id = item.input.approval_context_id or item.id
    scope = _build_approval_scope(approval_context_id, rt.backend, agent_name)

    # Reconstruct deferred tool results if this is a resumption
    deferred_results: DeferredToolResults | None = None
    if item.input.deferred_tool_results_json:
        deferred_results = _deserialize_deferred_results(
            item.input.deferred_tool_results_json,
            scope=scope,
            approval_store=rt.approval_store,
            key_manager=rt.key_manager,
        )

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
            # asyncio.run() creates a new event loop; breaks if called from an existing one
            # (e.g., inside an async web framework).

            async def _stream() -> WorkItemOutput:
                try:
                    async with rt.agent.run_stream(
                        prompt,
                        deps=deps,
                        message_history=history,
                        output_type=output_type,
                        deferred_tool_results=deferred_results,
                    ) as stream:
                        async for chunk in stream.stream_text(delta=True):
                            stream_handle.write(chunk)
                        result_output: AgentOutput = await stream.get_output()
                        all_msgs = stream.all_messages()
                finally:
                    stream_handle.close()

                if isinstance(result_output, DeferredToolRequests):
                    return WorkItemOutput(
                        deferred_tool_requests_json=_serialize_deferred_requests(
                            result_output,
                            scope=scope,
                            approval_store=rt.approval_store,
                            key_manager=rt.key_manager,
                            tool_policy=rt.tool_policy,
                        ),
                        message_history_json=_serialize_history(all_msgs),
                    )
                return WorkItemOutput(
                    text=result_output,
                    message_history_json=_serialize_history(all_msgs),
                )

            output = asyncio.run(_stream())
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
                    deferred_tool_requests_json=_serialize_deferred_requests(
                        result.output,
                        scope=scope,
                        approval_store=rt.approval_store,
                        key_manager=rt.key_manager,
                        tool_policy=rt.tool_policy,
                    ),
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


def _display_approval_requests(requests_json: str) -> dict[str, Any]:
    """Display pending tool approval requests and return the parsed list."""
    payload: dict[str, Any] = json.loads(requests_json)
    requests = cast(list[dict[str, Any]], payload["requests"])
    print("\n🔒 Tool approval required:")
    print(f"  Plan hash: {payload['plan_hash_prefix']}")
    for i, req in enumerate(requests, 1):
        tool_name = req["tool_name"]
        args: Any = req["args"]
        print(f"  [{i}] {tool_name}")
        serialized = json.dumps(args, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
        print("      args:")
        for line in serialized.splitlines():
            print(f"        {line}")
    return payload


def _decision_entry(tool_call_id: str, approved: bool) -> dict[str, Any]:
    return {
        "tool_call_id": tool_call_id,
        "approved": approved,
        "denial_message": None if approved else "User denied this action.",
    }


def _collect_single_decision(request: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        answer = input("  Approve? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    approved = answer in ("", "y", "yes")
    return [_decision_entry(str(request["tool_call_id"]), approved)]


def _collect_batch_decisions(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        answer = input("  Approve all? [Y/n/pick] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    if answer in ("", "y", "yes"):
        return [_decision_entry(str(req["tool_call_id"]), True) for req in requests]
    if answer in ("pick", "p"):
        decisions: list[dict[str, Any]] = []
        for i, req in enumerate(requests, 1):
            try:
                choice = input(f"  [{i}] {req['tool_name']} - approve? [Y/n] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "n"
            approved = choice in ("", "y", "yes")
            decisions.append(_decision_entry(str(req["tool_call_id"]), approved))
        return decisions
    return [_decision_entry(str(req["tool_call_id"]), False) for req in requests]


def _gather_approvals(
    payload: dict[str, Any], *, approval_store: ApprovalStore, key_manager: ApprovalKeyManager
) -> str:
    """Prompt the user for approval decisions on each tool call.

    Returns serialized JSON payload of approval decisions for
    ``_deserialize_deferred_results``.
    """
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise ValueError("Approval payload nonce is missing.")
    requests = cast(list[dict[str, Any]], payload["requests"])
    decisions = (
        _collect_single_decision(requests[0])
        if len(requests) == 1
        else _collect_batch_decisions(requests)
    )

    signed_decisions: list[SignedDecision] = [
        {"tool_call_id": str(item["tool_call_id"]), "approved": bool(item["approved"])}
        for item in decisions
    ]
    approval_store.store_signed_approval(
        nonce=nonce,
        decisions=signed_decisions,
        key_manager=key_manager,
    )
    return json.dumps({"nonce": nonce, "decisions": decisions}, ensure_ascii=True, allow_nan=False)


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
    rt = _get_runtime()
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
            approval_context_id = uuid4().hex

            # Approval loop — keeps re-enqueuing until we get a text response
            while True:
                item = WorkItem(
                    type=WorkItemType.CHAT,
                    priority=WorkItemPriority.CRITICAL,
                    input=WorkItemInput(
                        prompt=prompt,
                        message_history_json=history_json,
                        deferred_tool_results_json=deferred_results_json,
                        approval_context_id=approval_context_id,
                    ),
                )

                # Register a stream handle so the worker streams to stdout
                register_stream(item.id, PrintStreamHandle())

                output = enqueue_and_wait(item)
                history_json = output.message_history_json

                if output.deferred_tool_requests_json is not None:
                    # Agent wants tool approval — display and gather decisions
                    requests_payload = _display_approval_requests(
                        output.deferred_tool_requests_json
                    )
                    deferred_results_json = _gather_approvals(
                        requests_payload,
                        approval_store=rt.approval_store,
                        key_manager=rt.key_manager,
                    )
                    # Re-enqueue without prompt — context is in message history
                    prompt = None
                    continue

                # Normal text response — done with this turn
                break

        except ApprovalVerificationError as exc:
            print(f"Approval verification failed [{exc.code}]: {exc}", file=sys.stderr)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _rotate_key(base_dir: Path) -> None:
    approval_store = ApprovalStore.from_env(base_dir=base_dir)
    key_manager = ApprovalKeyManager.from_env(base_dir=base_dir)
    key_manager.rotate_key_interactive(expire_pending_envelopes=approval_store.expire_pending_envelopes)
    print("Approval signing key rotated. Pending approvals were expired.")


def main() -> None:
    """Load config, assemble runtime components, and launch DBOS + CLI chat.

    Startup order is intentional:
    1. load ``.env`` relative to this file
    2. parse command mode (chat or rotate-key)
    3. unlock approval signing key (or rotate and exit)
    4. build backend → toolsets → agent
    5. store runtime state for queue workers
    6. configure and launch DBOS
    7. enter interactive CLI chat loop (all input via queue)
    """
    base_dir = Path(__file__).resolve().parent
    load_dotenv(dotenv_path=base_dir / ".env")

    args = sys.argv[1:]
    if args:
        if len(args) == 1 and args[0] == "rotate-key":
            _rotate_key(base_dir)
            return
        raise SystemExit("Usage: python chat.py [rotate-key]")

    provider = os.getenv("AI_PROVIDER", "anthropic").lower()
    agent_name = os.getenv("DBOS_AGENT_NAME", "chat")

    backend = build_backend()
    approval_store = ApprovalStore.from_env(base_dir=base_dir)
    key_manager = ApprovalKeyManager.from_env(base_dir=base_dir)
    key_manager.ensure_unlocked_interactive()
    tool_policy = ToolPolicyRegistry.default()
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
    _set_runtime(agent, backend, history_db_path, approval_store, key_manager, tool_policy)
    DBOS(config=dbos_config)

    DBOS.launch()
    cli_chat_loop()


if __name__ == "__main__":
    main()
