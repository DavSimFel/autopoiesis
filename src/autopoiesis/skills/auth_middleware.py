"""Approval gate transform for skill tools requiring elevated approval tiers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from fastmcp.server.transforms import GetToolNext, Transform, VersionSpec
from fastmcp.tools.tool import Tool, ToolResult
from pydantic import PrivateAttr

_TIER_ORDER: dict[str, int] = {
    "free": 0,
    "review": 1,
    "approve": 2,
    "block": 3,
}
_APPROVAL_THRESHOLD = _TIER_ORDER["approve"]


class _ApprovalGateTool(Tool):
    """Tool wrapper that blocks execution until approval unlock is active."""

    _delegate: Tool = PrivateAttr()
    _required_tier: str = PrivateAttr()
    _unlock_check: Callable[[], bool] = PrivateAttr()

    @classmethod
    def wrap(
        cls,
        tool: Tool,
        *,
        required_tier: str,
        unlock_check: Callable[[], bool],
    ) -> _ApprovalGateTool:
        if isinstance(tool, _ApprovalGateTool):
            return tool
        wrapped = cls(**_copy_tool_kwargs(tool))
        wrapped._delegate = tool
        wrapped._required_tier = required_tier
        wrapped._unlock_check = unlock_check
        return wrapped

    def model_copy(self, **kwargs: Any) -> _ApprovalGateTool:
        copied = cast(_ApprovalGateTool, super().model_copy(**kwargs))
        copied._delegate = self._delegate
        copied._required_tier = self._required_tier
        copied._unlock_check = self._unlock_check
        return copied

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        return await self._delegate.run(arguments)

    def _blocked_result(self) -> ToolResult | None:
        if self._unlock_check():
            return None
        return ToolResult(
            content=(
                "Approval required: this tool needs an active approval unlock "
                f"(required tier: {self._required_tier})."
            ),
            meta={
                "blocked": True,
                "reason": "approval_required",
                "required_tier": self._required_tier,
            },
        )


class ApprovalGateTransform(Transform):
    """Gate tools requiring APPROVE+ tiers behind active approval unlock."""

    def __init__(
        self,
        *,
        tool_tiers: Mapping[str, str] | None = None,
        unlock_check: Callable[[], bool] | None = None,
    ) -> None:
        normalized_tiers = tool_tiers or {}
        self._tool_tiers: dict[str, str] = {
            name: _normalize_tier(value) for name, value in normalized_tiers.items()
        }
        self._unlock_check = unlock_check or _default_unlock_check

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return [self._wrap_tool(tool) for tool in tools]

    async def get_tool(
        self,
        name: str,
        call_next: GetToolNext,
        *,
        version: VersionSpec | None = None,
    ) -> Tool | None:
        tool = await call_next(name, version=version)
        if tool is None:
            return None
        return self._wrap_tool(tool)

    def _wrap_tool(self, tool: Tool) -> Tool:
        tier = _resolve_required_tier(tool, self._tool_tiers)
        if tier is None:
            return tool
        if _TIER_ORDER[tier] < _APPROVAL_THRESHOLD:
            return tool
        return _ApprovalGateTool.wrap(
            tool, required_tier=tier, unlock_check=self._unlock_check,
        )


def load_skill_approval_tiers(skill_root: str | Path) -> dict[str, str]:
    """Load per-tool approval tiers from ``skill.yaml`` if present."""
    loaded = _load_skill_yaml(Path(skill_root))
    if loaded is None:
        return {}
    return _extract_tier_overrides(loaded)


def _load_skill_yaml(skill_dir: Path) -> dict[str, object] | None:
    config_path = skill_dir / "skill.yaml"
    if not config_path.exists():
        return None
    try:
        import yaml  # type: ignore[import-untyped]
    except ModuleNotFoundError:
        return None
    try:
        loaded: object = yaml.safe_load(config_path.read_text())
    except (OSError, yaml.YAMLError):
        return None
    return cast(dict[str, object], loaded) if isinstance(loaded, dict) else None


def _extract_tier_overrides(loaded: dict[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    _copy_direct_tiers(loaded.get("tool_approval_tiers"), result)
    _copy_nested_tiers(loaded.get("tools"), result)
    return result


def _copy_direct_tiers(raw: object, target: dict[str, str]) -> None:
    if not isinstance(raw, dict):
        return
    mapping = cast(dict[object, object], raw)
    for tool_name, tier in mapping.items():
        if isinstance(tool_name, str) and isinstance(tier, str):
            target[tool_name] = _normalize_tier(tier)


def _copy_nested_tiers(raw: object, target: dict[str, str]) -> None:
    if not isinstance(raw, dict):
        return
    mapping = cast(dict[object, object], raw)
    for tool_name, config in mapping.items():
        if not isinstance(tool_name, str) or not isinstance(config, dict):
            continue
        tier: object = cast(dict[str, object], config).get("approval_tier")
        if isinstance(tier, str):
            target[tool_name] = _normalize_tier(tier)


def _resolve_required_tier(tool: Tool, tool_tiers: Mapping[str, str]) -> str | None:
    if tool.name in tool_tiers:
        return tool_tiers[tool.name]
    tier_from_meta = _tier_from_meta(tool.meta)
    if tier_from_meta is not None:
        return tier_from_meta
    for tag in tool.tags:
        for prefix in ("tier:", "approval:"):
            if tag.startswith(prefix):
                raw = tag[len(prefix):]
                if raw:
                    return _normalize_tier(raw)
    return None


def _tier_from_meta(meta: dict[str, Any] | None) -> str | None:
    if meta is None:
        return None
    direct: object = meta.get("approval_tier")
    if isinstance(direct, str):
        return _normalize_tier(direct)
    for block_key in ("security", "autopoiesis"):
        block: object = meta.get(block_key)
        if isinstance(block, dict):
            nested: object = cast(dict[str, object], block).get("approval_tier")
            if isinstance(nested, str):
                return _normalize_tier(nested)
    return None


def _normalize_tier(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized in _TIER_ORDER else "approve"


def _default_unlock_check() -> bool:
    """Read approval unlock state via approval policy integration hooks."""
    try:
        policy_module = import_module("autopoiesis.infra.approval.policy")
    except ModuleNotFoundError:
        return False
    for attr_name in ("approval_unlock_active", "is_approval_unlocked"):
        checker: object = getattr(policy_module, attr_name, None)
        if callable(checker):
            try:
                return bool(checker())
            except (TypeError, ValueError):
                continue
    fallback_value: object = getattr(policy_module, "approval_unlocked", None)
    return bool(fallback_value) if isinstance(fallback_value, bool) else False


def _copy_tool_kwargs(tool: Tool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "version": tool.version,
        "title": tool.title,
        "description": tool.description,
        "icons": list(tool.icons) if tool.icons is not None else None,
        "tags": set(tool.tags),
        "meta": dict(tool.meta) if tool.meta is not None else None,
        "task_config": tool.task_config,
        "parameters": dict(tool.parameters),
        "output_schema": dict(tool.output_schema) if tool.output_schema is not None else None,
        "annotations": tool.annotations,
        "execution": tool.execution,
        "serializer": tool.serializer,
        "auth": tool.auth,
        "timeout": tool.timeout,
    }
