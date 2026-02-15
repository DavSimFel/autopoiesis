"""Compatibility re-exports for legacy imports.

This module keeps existing imports stable while the implementation lives in
specialized modules.
"""

from approval_store import ApprovalStore
from approval_types import ApprovalScope, ApprovalVerificationError

__all__ = ["ApprovalScope", "ApprovalStore", "ApprovalVerificationError"]
