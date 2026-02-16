"""Cryptographic approval subsystem.

Public API: ApprovalStore, ApprovalKeyManager, ToolPolicyRegistry
Internal: crypto, key_files, store_schema, store_verify, chat_approval, types
"""

from approval.chat_approval import (
    build_approval_scope,
    deserialize_deferred_results,
    display_approval_requests,
    gather_approvals,
    serialize_deferred_requests,
)
from approval.keys import ApprovalKeyManager
from approval.policy import ToolPolicyRegistry
from approval.store import ApprovalStore
from approval.types import (
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
