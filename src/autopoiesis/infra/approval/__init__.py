"""Cryptographic approval subsystem.

Public API: ApprovalKeyManager, ApprovalScope, ApprovalStore,
    ApprovalVerificationError, DeferredToolCall, SignedDecision,
    ToolPolicyRegistry, build_approval_scope,
    deserialize_deferred_results, display_approval_requests,
    gather_approvals, serialize_deferred_requests
Internal: crypto, key_files, store_schema, store_verify, chat_approval, types
"""

from autopoiesis.infra.approval.chat_approval import (
    build_approval_scope,
    deserialize_deferred_results,
    display_approval_requests,
    gather_approvals,
    serialize_deferred_requests,
)
from autopoiesis.infra.approval.keys import ApprovalKeyManager
from autopoiesis.infra.approval.policy import ToolPolicyRegistry
from autopoiesis.infra.approval.store import ApprovalStore
from autopoiesis.infra.approval.types import (
    ApprovalScope,
    ApprovalVerificationError,
    DeferredToolCall,
    SignedDecision,
)

__all__ = [
    "ApprovalKeyManager",
    "ApprovalScope",
    "ApprovalStore",
    "ApprovalVerificationError",
    "DeferredToolCall",
    "SignedDecision",
    "ToolPolicyRegistry",
    "build_approval_scope",
    "deserialize_deferred_results",
    "display_approval_requests",
    "gather_approvals",
    "serialize_deferred_requests",
]
