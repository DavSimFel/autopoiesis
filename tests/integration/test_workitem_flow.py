"""Section 7: WorkItem Inter-Agent Flow (3-Tier).

These tests define the full planner to coder to reviewer loop.
All blocked on #146 Phase A (multi-agent runtime) + WorkItem routing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SKIP_REASON = "Blocked on #146 Phase A - multi-agent WorkItem flow not implemented"

pytestmark = pytest.mark.skip(reason=_SKIP_REASON)


def write_topic(topics_dir: Path, name: str, content: str) -> Path:
    p = topics_dir / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return p


_FIX_BUG_OPEN = "---\ntype: task\nstatus: open\nowner: coder\n---\nFix the bug."
_FIX_BUG_WIP = "---\ntype: task\nstatus: in-progress\nowner: coder\n---\nFix the bug."
_FIX_BUG_REVIEW = "---\ntype: task\nstatus: review\nowner: reviewer\n---\nFix the bug."
_FEATURE_OPEN = "---\ntype: task\nstatus: open\n---\nBuild feature X."


class TestPlannerToCoderFlow:
    """7.1 - Planner creates WorkItem for Coder."""

    def test_planner_enqueues_workitem_for_coder(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "fix-bug", _FIX_BUG_OPEN)
        raise NotImplementedError("Multi-agent WorkItem dispatch not yet implemented")


class TestCoderToReviewerFlow:
    """7.2 - Coder finishes, WorkItem to Reviewer."""

    def test_status_review_triggers_reviewer_workitem(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "fix-bug", _FIX_BUG_WIP)
        raise NotImplementedError("Status-triggered routing not yet implemented")


class TestReviewerRejectsFlow:
    """7.3 - Reviewer rejects, back to Coder."""

    def test_reject_routes_back_to_coder(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "fix-bug", _FIX_BUG_REVIEW)
        raise NotImplementedError("Rejection routing not yet implemented")


class TestReviewerApprovesFlow:
    """7.4 - Reviewer approves, back to Planner."""

    def test_approve_routes_to_planner(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "fix-bug", _FIX_BUG_REVIEW)
        raise NotImplementedError("Approval routing not yet implemented")


class TestFullWorkItemLoop:
    """7.5 - Full loop: open to in-progress to review to done."""

    def test_complete_3_tier_lifecycle(self, topics_dir: Path) -> None:
        write_topic(topics_dir, "feature-x", _FEATURE_OPEN)
        raise NotImplementedError("Full 3-tier loop not yet implemented")
