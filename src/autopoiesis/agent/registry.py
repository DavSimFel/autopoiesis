"""Thread-safe agent-keyed runtime registry (Issue #203).

Extracted from :mod:`autopoiesis.agent.runtime` to keep that module within
the 300-line architectural limit.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autopoiesis.agent.runtime import Runtime


class AgentRegistry:
    """Thread-safe registry that maps *agent_id* → :class:`Runtime`.

    Replaces the previous single-instance ``RuntimeRegistry`` so that multiple
    agents can each hold their own :class:`Runtime` without sharing state.

    Backward-compatible entry-points
    ---------------------------------
    * :meth:`set` - stores a runtime under the sentinel key
      ``"__default__"`` so that existing call-sites that do not supply an
      *agent_id* continue to work.
    * :meth:`get` (with no *agent_id*) - returns the sole registered runtime
      when exactly one is present, or the ``"__default__"`` runtime when
      multiple runtimes exist.  Raises :class:`RuntimeError` when nothing has
      been registered yet.

    Primary multi-agent entry-points
    ---------------------------------
    * :meth:`register` - store a runtime under an explicit *agent_id*.
    * :meth:`get` (with *agent_id*) - retrieve the runtime for that agent,
      raising :class:`RuntimeError` when the agent has not been registered.
    * :meth:`list_agents` - return the currently registered agent IDs
      (excludes the ``"__default__"`` sentinel key).
    """

    _DEFAULT_KEY: str = "__default__"

    def __init__(self) -> None:
        self._runtimes: dict[str, Runtime] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Primary multi-agent API
    # ------------------------------------------------------------------

    def register(self, agent_id: str, runtime: Runtime) -> None:
        """Register *runtime* under *agent_id*, replacing any existing entry."""
        with self._lock:
            self._runtimes[agent_id] = runtime

    def get(self, agent_id: str | None = None) -> Runtime:
        """Return the :class:`Runtime` for *agent_id*.

        When *agent_id* is ``None``:

        * If exactly one runtime is registered (or only the ``"__default__"``
          sentinel is present), it is returned.
        * If multiple runtimes are registered the ``"__default__"`` entry is
          returned when present.
        * Otherwise :class:`RuntimeError` is raised.
        """
        with self._lock:
            runtimes = dict(self._runtimes)

        if agent_id is not None:
            rt = runtimes.get(agent_id)
            if rt is None:
                visible = sorted(k for k in runtimes if k != self._DEFAULT_KEY)
                registered = ", ".join(visible) if visible else "none"
                raise RuntimeError(
                    f"No runtime registered for agent '{agent_id}'. "
                    f"Registered agents: {registered}."
                )
            return rt

        # --- backward-compatible single-runtime access ---
        if not runtimes:
            raise RuntimeError("Runtime not initialised. Start the app via main().")
        if len(runtimes) == 1:
            return next(iter(runtimes.values()))
        # Multiple runtimes: return default sentinel if present.
        default = runtimes.get(self._DEFAULT_KEY)
        if default is not None:
            return default
        visible = sorted(k for k in runtimes if k != self._DEFAULT_KEY)
        raise RuntimeError(
            f"Multiple runtimes registered ({', '.join(visible)}). "
            "Call get_runtime(agent_id=...) to select one."
        )

    def reset(self, agent_id: str | None = None) -> None:
        """Clear the registry.

        When *agent_id* is given only that agent's entry is removed; when
        ``None`` the entire registry is cleared (useful for testing).
        """
        with self._lock:
            if agent_id is None:
                self._runtimes.clear()
            else:
                self._runtimes.pop(agent_id, None)

    def list_agents(self) -> list[str]:
        """Return sorted agent IDs that have registered runtimes.

        The ``"__default__"`` sentinel (used by the backward-compatible
        :meth:`set` path) is excluded from the returned list.
        """
        with self._lock:
            return sorted(k for k in self._runtimes if k != self._DEFAULT_KEY)

    # ------------------------------------------------------------------
    # Backward-compatible single-runtime API
    # ------------------------------------------------------------------

    def set(self, runtime: Runtime) -> None:
        """Register *runtime* under the ``"__default__"`` sentinel key.

        Preserves call-site compatibility with the old ``RuntimeRegistry.set``
        method.
        """
        self.register(self._DEFAULT_KEY, runtime)


#: Backward-compatible alias so that existing imports of ``RuntimeRegistry``
#: continue to resolve without modification.
RuntimeRegistry = AgentRegistry
