"""Extended subscription integration tests — lines/knowledge kinds, regex, path escapes."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from autopoiesis.infra.subscription_processor import (
    is_materialization,
    materialize_subscriptions,
)
from autopoiesis.store.subscriptions import SubscriptionRegistry


class TestLinesSubscriptionKind:
    """Lines subscription with line_range slicing."""

    def test_lines_subscription_slices_content(
        self,
        workspace_root: Path,
        subscription_registry: SubscriptionRegistry,
        knowledge_db: str,
    ) -> None:
        target = workspace_root / "big.py"
        target.write_text("\n".join(f"line {i}" for i in range(1, 21)))

        subscription_registry.add("lines", "big.py", line_range=(5, 10))

        msgs: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="check")])]
        result = materialize_subscriptions(
            msgs, subscription_registry, workspace_root, knowledge_db
        )
        mat = result[0]
        assert isinstance(mat, ModelRequest)
        content = str(mat.parts[0].content)
        assert "line 5" in content
        assert "line 10" in content
        # Lines outside range should not appear
        assert "line 1\n" not in content
        assert "line 20" not in content


class TestKnowledgeSubscriptionKind:
    """Knowledge subscription runs FTS query."""

    def test_knowledge_subscription_returns_results(
        self,
        workspace_root: Path,
        tmp_path: Path,
        knowledge_db: str,
    ) -> None:
        from autopoiesis.store.knowledge import index_file, init_knowledge_index

        knowledge_root = tmp_path / "knowledge"
        knowledge_root.mkdir()
        doc = knowledge_root / "notes.md"
        doc.write_text("# Integration testing\nPytest fixtures are powerful tools.\n")
        init_knowledge_index(knowledge_db)
        index_file(knowledge_db, knowledge_root, doc)

        db_path = str(tmp_path / "subs_knowledge.sqlite")
        registry = SubscriptionRegistry(db_path, session_id="test-knowledge")
        registry.add("knowledge", "pytest fixtures")

        msgs: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="check")])]
        result = materialize_subscriptions(msgs, registry, workspace_root, knowledge_db)
        # Should have materialization + original message
        assert len(result) == 2
        mat = result[0]
        assert is_materialization(mat)


class TestRegexPatternFailure:
    """Invalid regex in subscription pattern returns error gracefully."""

    def test_invalid_regex_returns_error(
        self,
        workspace_root: Path,
        subscription_registry: SubscriptionRegistry,
        knowledge_db: str,
    ) -> None:
        target = workspace_root / "code.py"
        target.write_text("def foo():\n    pass\n")

        subscription_registry.add("file", "code.py", pattern="[invalid")

        msgs: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="check")])]
        result = materialize_subscriptions(
            msgs, subscription_registry, workspace_root, knowledge_db
        )
        mat = result[0]
        assert isinstance(mat, ModelRequest)
        content = str(mat.parts[0].content)
        assert "Error" in content or "invalid pattern" in content


class TestPathEscapeProtection:
    """Subscription targeting path outside workspace is blocked."""

    def test_path_escape_blocked(
        self,
        workspace_root: Path,
        subscription_registry: SubscriptionRegistry,
        knowledge_db: str,
    ) -> None:
        # Create a file outside workspace
        outside = workspace_root.parent / "secret.txt"
        outside.write_text("secret data")

        subscription_registry.add("file", "../secret.txt")

        msgs: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="check")])]
        result = materialize_subscriptions(
            msgs, subscription_registry, workspace_root, knowledge_db
        )
        mat = result[0]
        assert isinstance(mat, ModelRequest)
        content = str(mat.parts[0].content)
        assert "secret data" not in content
        assert "Error" in content or "escapes" in content


class TestMaterializationReplacement:
    """Old materialization messages are stripped and replaced with fresh ones."""

    def test_old_materialization_replaced(
        self,
        workspace_root: Path,
        subscription_registry: SubscriptionRegistry,
        knowledge_db: str,
    ) -> None:
        target = workspace_root / "data.txt"
        target.write_text("version 1")
        subscription_registry.add("file", "data.txt")

        msgs: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="turn 1")])]
        result1 = materialize_subscriptions(
            msgs, subscription_registry, workspace_root, knowledge_db
        )

        # Now update file and pass result1 as history
        target.write_text("version 2")
        result1.append(ModelRequest(parts=[UserPromptPart(content="turn 2")]))
        result2 = materialize_subscriptions(
            result1, subscription_registry, workspace_root, knowledge_db
        )

        # Should only have ONE materialization message (old one replaced)
        mat_count = sum(1 for m in result2 if is_materialization(m))
        assert mat_count == 1

        # Content should be fresh
        for m in result2:
            if is_materialization(m):
                assert isinstance(m, ModelRequest)
                content = str(m.parts[0].content)
                assert "version 2" in content
