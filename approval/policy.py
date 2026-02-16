"""Immutable tool classification policy for deferred approvals."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from approval.types import ApprovalVerificationError, DeferredToolCall


class ToolClassification(StrEnum):
    """Classification for deferred approval policy decisions."""

    SIDE_EFFECTING = "side_effecting"
    READ_ONLY = "read_only"


_DEFAULT_READ_ONLY_TOOLS = frozenset(
    {
        "ls",
        "ls_info",
        "read",
        "read_file",
        "glob",
        "glob_info",
        "grep",
        "grep_raw",
        "process_list",
        "process_poll",
        "process_log",
    }
)


class ToolPolicyRegistry:
    """Immutable registry that defaults unknown tools to side-effecting."""

    def __init__(self, mapping: Mapping[str, ToolClassification]) -> None:
        self._mapping = MappingProxyType(dict(mapping))

    @classmethod
    def default(cls) -> ToolPolicyRegistry:
        mapping = dict.fromkeys(sorted(_DEFAULT_READ_ONLY_TOOLS), ToolClassification.READ_ONLY)
        return cls(mapping)

    def classify(self, tool_name: str) -> ToolClassification:
        return self._mapping.get(tool_name, ToolClassification.SIDE_EFFECTING)

    def validate_deferred_calls(self, tool_calls: list[DeferredToolCall]) -> None:
        for call in tool_calls:
            classification = self.classify(call["tool_name"])
            if classification is ToolClassification.READ_ONLY:
                raise ApprovalVerificationError(
                    "tool_policy_violation",
                    f"Read-only tool '{call['tool_name']}' must not require deferred approval.",
                )
