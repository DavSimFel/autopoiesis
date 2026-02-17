"""Section 4: Subscription Pipeline integration tests.

Tests 4.1-4.2 (file subscriptions) work today. Test 4.3 (topic subscription
kind) is blocked on #150 Phase 2. Tests 4.4-4.5 (limits, expiry) work today.
"""

from __future__ import annotations

import time
from contextlib import closing
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from autopoiesis.db import open_db
from autopoiesis.infra.subscription_processor import (
    is_materialization,
    materialize_subscriptions,
)
from autopoiesis.store.subscriptions import (
    EXPIRY_SECONDS,
    MAX_SUBSCRIPTIONS,
    SubscriptionRegistry,
)


class TestFileSubscriptionMaterializes:
    """4.1 - File subscription materializes content into agent context."""

    def test_file_content_injected(
        self,
        workspace_root: Path,
        subscription_registry: SubscriptionRegistry,
        knowledge_db: str,
    ) -> None:
        src_file = workspace_root / "src" / "chat.py"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("def main():\n    print('hello')\n")

        subscription_registry.add("file", "src/chat.py")

        user_msg = ModelRequest(parts=[UserPromptPart(content="What does chat.py do?")])
        messages: list[ModelMessage] = [user_msg]

        result = materialize_subscriptions(
            messages, subscription_registry, workspace_root, knowledge_db
        )

        assert len(result) == 2
        mat_msg = result[0]
        assert is_materialization(mat_msg)
        assert isinstance(mat_msg, ModelRequest)
        content = str(mat_msg.parts[0].content)  # type: ignore[union-attr]
        assert "chat.py" in content


class TestFileChangesReflected:
    """4.2 - File changes reflected next turn."""

    def test_updated_content_appears(
        self,
        workspace_root: Path,
        subscription_registry: SubscriptionRegistry,
        knowledge_db: str,
    ) -> None:
        target = workspace_root / "config.yaml"
        target.write_text("version: 1\n")
        subscription_registry.add("file", "config.yaml")

        msgs: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="check")])]
        result1 = materialize_subscriptions(
            msgs, subscription_registry, workspace_root, knowledge_db
        )
        mat1 = result1[0]
        assert isinstance(mat1, ModelRequest)
        content1 = str(mat1.parts[0].content)  # type: ignore[union-attr]
        assert "version: 1" in content1

        target.write_text("version: 2\n")

        msgs2: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="check again")])]
        result2 = materialize_subscriptions(
            msgs2, subscription_registry, workspace_root, knowledge_db
        )
        mat2 = result2[0]
        assert isinstance(mat2, ModelRequest)
        content2 = str(mat2.parts[0].content)  # type: ignore[union-attr]
        assert "version: 2" in content2


class TestTopicSubscriptionKind:
    """4.3 - Topic subscription fires on status change.

    Blocked on #150 Phase 2: topic subscription kind not yet implemented.
    """

    @pytest.mark.skip(reason="Blocked on #150 Phase 2 - topic subscription kind")
    def test_topic_status_change_materializes(
        self,
        workspace_root: Path,
        tmp_path: Path,
    ) -> None:
        raise NotImplementedError("Topic subscription kind not yet implemented")


class TestMaxSubscriptionsEnforced:
    """4.4 - Max subscriptions enforced."""

    def test_eleventh_subscription_raises(
        self,
        subscription_registry: SubscriptionRegistry,
    ) -> None:
        for i in range(MAX_SUBSCRIPTIONS):
            subscription_registry.add("file", f"file-{i}.txt")

        with pytest.raises(ValueError, match="limit"):
            subscription_registry.add("file", "one-too-many.txt")


class TestExpiredSubscriptionsCleanup:
    """4.5 - Expired subscriptions cleaned up."""

    def test_stale_subscriptions_removed(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "subs_expiry.sqlite")
        registry = SubscriptionRegistry(db_path, session_id="expiry-test")
        registry.add("file", "old-file.txt")

        with closing(open_db(Path(db_path))) as conn, conn:
            conn.execute(
                "UPDATE subscriptions SET created_at = ?",
                (time.time() - EXPIRY_SECONDS - 100,),
            )
            conn.commit()

        assert len(registry.get_active()) == 0
        deleted = registry.expire_stale()
        assert deleted >= 1
