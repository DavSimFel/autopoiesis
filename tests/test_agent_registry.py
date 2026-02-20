"""Tests for the agent-keyed runtime registry (Issue #203).

Verifies that AgentRegistry maps agent_id → Runtime, that multiple
runtimes coexist without interference, and that backward-compatible
single-runtime usage still works.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from autopoiesis.agent.runtime import (
    AgentRegistry,
    Runtime,
    RuntimeRegistry,
    get_agent_registry,
    get_runtime,
    get_runtime_registry,
    register_runtime,
    reset_runtime,
    set_agent_registry,
    set_runtime,
    set_runtime_registry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime(**kwargs: object) -> Runtime:
    """Return a mock Runtime with sensible defaults for testing."""
    defaults: dict[str, object] = {
        "agent": MagicMock(),
        "backend": MagicMock(),
        "history_db_path": "/tmp/h.sqlite",
        "knowledge_db_path": "/tmp/k.sqlite",
        "subscription_registry": None,
        "approval_store": MagicMock(),
        "key_manager": MagicMock(),
        "tool_policy": MagicMock(),
        "shell_tier": "review",
    }
    defaults.update(kwargs)
    return cast(Runtime, MagicMock(spec=Runtime, **defaults))  # type: ignore[misc]  # pyright: ignore[reportCallIssue]


# ---------------------------------------------------------------------------
# 203.1 — AgentRegistry basic contract
# ---------------------------------------------------------------------------


class TestAgentRegistryBasic:
    """AgentRegistry stores and retrieves runtimes by agent_id."""

    def test_empty_registry_raises_on_get(self) -> None:
        """get() with no registered runtimes raises RuntimeError."""
        registry = AgentRegistry()
        with pytest.raises(RuntimeError, match="Runtime not initialised"):
            registry.get()

    def test_register_and_get_by_agent_id(self) -> None:
        """register + get(agent_id) round-trip works."""
        registry = AgentRegistry()
        rt = _make_runtime()
        registry.register("alpha", rt)
        assert registry.get("alpha") is rt

    def test_get_unknown_agent_raises(self) -> None:
        """get(agent_id) for unknown agent raises RuntimeError with helpful message."""
        registry = AgentRegistry()
        rt = _make_runtime()
        registry.register("alpha", rt)
        with pytest.raises(RuntimeError, match="beta"):
            registry.get("beta")

    def test_get_error_message_lists_registered_agents(self) -> None:
        """RuntimeError from get() names the registered agents."""
        registry = AgentRegistry()
        registry.register("alpha", _make_runtime())
        registry.register("gamma", _make_runtime())
        with pytest.raises(RuntimeError, match="alpha"):
            registry.get("unknown-agent")

    def test_register_replaces_existing(self) -> None:
        """Re-registering the same agent_id replaces the previous runtime."""
        registry = AgentRegistry()
        rt1 = _make_runtime()
        rt2 = _make_runtime()
        registry.register("alpha", rt1)
        registry.register("alpha", rt2)
        assert registry.get("alpha") is rt2

    def test_list_agents_empty(self) -> None:
        """list_agents() returns empty list when nothing is registered."""
        registry = AgentRegistry()
        assert registry.list_agents() == []

    def test_list_agents_returns_registered_ids(self) -> None:
        """list_agents() returns all registered agent IDs (sorted)."""
        registry = AgentRegistry()
        registry.register("beta", _make_runtime())
        registry.register("alpha", _make_runtime())
        assert registry.list_agents() == ["alpha", "beta"]

    def test_list_agents_excludes_default_sentinel(self) -> None:
        """list_agents() excludes the '__default__' sentinel used by set()."""
        registry = AgentRegistry()
        registry.set(_make_runtime())  # stores under __default__
        registry.register("alpha", _make_runtime())
        agents = registry.list_agents()
        assert "__default__" not in agents
        assert "alpha" in agents


# ---------------------------------------------------------------------------
# 203.2 — Multiple runtimes coexist without interference
# ---------------------------------------------------------------------------


class TestMultipleRuntimesIsolation:
    """Multiple runtimes keyed by agent_id do not share state."""

    def test_two_agents_get_different_runtimes(self) -> None:
        """Registering separate runtimes for alpha and beta keeps them isolated."""
        registry = AgentRegistry()
        rt_alpha = _make_runtime(history_db_path="/tmp/alpha.sqlite")
        rt_beta = _make_runtime(history_db_path="/tmp/beta.sqlite")

        registry.register("alpha", rt_alpha)
        registry.register("beta", rt_beta)

        assert registry.get("alpha") is rt_alpha
        assert registry.get("beta") is rt_beta
        assert registry.get("alpha") is not registry.get("beta")

    def test_updating_alpha_does_not_affect_beta(self) -> None:
        """Replacing alpha's runtime does not change beta's entry."""
        registry = AgentRegistry()
        rt_alpha_v1 = _make_runtime()
        rt_alpha_v2 = _make_runtime()
        rt_beta = _make_runtime()

        registry.register("alpha", rt_alpha_v1)
        registry.register("beta", rt_beta)
        registry.register("alpha", rt_alpha_v2)  # replace

        assert registry.get("alpha") is rt_alpha_v2
        assert registry.get("beta") is rt_beta  # unchanged

    def test_resetting_one_agent_leaves_others(self) -> None:
        """reset(agent_id) removes only the specified agent's runtime."""
        registry = AgentRegistry()
        registry.register("alpha", _make_runtime())
        registry.register("beta", _make_runtime())

        registry.reset("alpha")

        with pytest.raises(RuntimeError, match="alpha"):
            registry.get("alpha")
        # beta's runtime is unaffected
        assert registry.get("beta") is not None

    def test_many_agents_registered(self) -> None:
        """Registry handles many simultaneous agents."""
        registry = AgentRegistry()
        runtimes = {f"agent-{i}": _make_runtime() for i in range(10)}
        for agent_id, rt in runtimes.items():
            registry.register(agent_id, rt)

        for agent_id, expected_rt in runtimes.items():
            assert registry.get(agent_id) is expected_rt

        assert sorted(registry.list_agents()) == sorted(runtimes)


# ---------------------------------------------------------------------------
# 203.3 — Backward-compatible single-runtime access
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Backward-compatible set/get/reset behaviour is preserved."""

    def test_set_then_get_no_agent_id(self) -> None:
        """set() + get() (no agent_id) round-trip works like the old RuntimeRegistry."""
        registry = AgentRegistry()
        rt = _make_runtime()
        registry.set(rt)
        assert registry.get() is rt

    def test_get_single_explicit_runtime_no_agent_id(self) -> None:
        """When exactly one named runtime is registered, get() returns it."""
        registry = AgentRegistry()
        rt = _make_runtime()
        registry.register("alpha", rt)
        assert registry.get() is rt  # sole runtime → no ambiguity

    def test_get_no_agent_id_multiple_runtimes_returns_default(self) -> None:
        """When multiple runtimes exist, get() returns the '__default__' entry."""
        registry = AgentRegistry()
        rt_default = _make_runtime()
        rt_alpha = _make_runtime()
        registry.set(rt_default)  # __default__
        registry.register("alpha", rt_alpha)
        assert registry.get() is rt_default

    def test_get_no_agent_id_multiple_without_default_raises(self) -> None:
        """get() without agent_id raises when multiple named runtimes exist."""
        registry = AgentRegistry()
        registry.register("alpha", _make_runtime())
        registry.register("beta", _make_runtime())
        with pytest.raises(RuntimeError, match="Multiple runtimes"):
            registry.get()

    def test_reset_no_agent_id_clears_all(self) -> None:
        """reset() (no agent_id) clears everything."""
        registry = AgentRegistry()
        registry.register("alpha", _make_runtime())
        registry.register("beta", _make_runtime())
        registry.reset()
        assert registry.list_agents() == []
        with pytest.raises(RuntimeError, match="Runtime not initialised"):
            registry.get()

    def test_runtime_registry_alias_works(self) -> None:
        """RuntimeRegistry is an alias for AgentRegistry and behaves identically."""
        assert RuntimeRegistry is AgentRegistry
        registry = RuntimeRegistry()
        rt = _make_runtime()
        registry.set(rt)
        assert registry.get() is rt
        registry.reset()
        with pytest.raises(RuntimeError, match="Runtime not initialised"):
            registry.get()


# ---------------------------------------------------------------------------
# 203.4 — Module-level convenience wrappers
# ---------------------------------------------------------------------------


class TestModuleLevelWrappers:
    """Module-level get_runtime / set_runtime / register_runtime / reset_runtime."""

    def test_register_then_get_runtime_by_agent_id(self) -> None:
        """register_runtime + get_runtime(agent_id) round-trip works."""
        registry = AgentRegistry()
        prev = set_agent_registry(registry)
        try:
            rt = _make_runtime()
            register_runtime("agent-x", rt)
            assert get_runtime("agent-x") is rt
        finally:
            set_agent_registry(prev)

    def test_set_runtime_backward_compat(self) -> None:
        """set_runtime() + get_runtime() (no agent_id) still works."""
        registry = AgentRegistry()
        prev = set_agent_registry(registry)
        try:
            rt = _make_runtime()
            set_runtime(rt)
            assert get_runtime() is rt
        finally:
            set_agent_registry(prev)

    def test_reset_runtime_specific_agent(self) -> None:
        """reset_runtime(agent_id) removes only the specified agent."""
        registry = AgentRegistry()
        prev = set_agent_registry(registry)
        try:
            rt_a = _make_runtime()
            rt_b = _make_runtime()
            register_runtime("a", rt_a)
            register_runtime("b", rt_b)

            reset_runtime("a")

            with pytest.raises(RuntimeError, match="'a'"):
                get_runtime("a")
            assert get_runtime("b") is rt_b
        finally:
            set_agent_registry(prev)

    def test_get_agent_registry_returns_same_as_get_runtime_registry(self) -> None:
        """get_agent_registry() and get_runtime_registry() return the same object."""
        assert get_agent_registry() is get_runtime_registry()

    def test_set_runtime_registry_and_set_agent_registry_are_equivalent(self) -> None:
        """set_runtime_registry and set_agent_registry both swap the active registry."""
        new_registry = AgentRegistry()
        prev = set_runtime_registry(new_registry)
        try:
            assert get_agent_registry() is new_registry
            assert get_runtime_registry() is new_registry
        finally:
            set_runtime_registry(prev)


# ---------------------------------------------------------------------------
# 203.5 — Thread safety (smoke test)
# ---------------------------------------------------------------------------


class TestAgentRegistryThreadSafety:
    """Concurrent writes to AgentRegistry do not corrupt state."""

    def test_concurrent_register_and_get(self) -> None:
        """Multiple threads can register and retrieve runtimes concurrently."""
        import threading

        registry = AgentRegistry()
        errors: list[Exception] = []

        def _worker(agent_id: str) -> None:
            try:
                rt = _make_runtime()
                registry.register(agent_id, rt)
                retrieved = registry.get(agent_id)
                # Should return *some* runtime (may have been replaced by
                # a concurrent thread for the same id, but must not be None)
                assert retrieved is not None
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(f"agent-{i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
