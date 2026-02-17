"""FastAPI application setup and route registration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from autopoiesis.server.connections import ConnectionManager
from autopoiesis.server.routes import configure_routes, router
from autopoiesis.server.sessions import SessionStore

_log = logging.getLogger(__name__)

_manager = ConnectionManager()
_sessions = SessionStore()

_SESSION_TTL_SECONDS: int = 30 * 60  # 30 minutes
_CLEANUP_INTERVAL_SECONDS: int = 5 * 60  # check every 5 minutes
_cleanup_task: asyncio.Task[None] | None = None  # set during lifespan


def get_connection_manager() -> ConnectionManager:
    """Return the global connection manager."""
    return _manager


def set_connection_manager(manager: ConnectionManager) -> None:
    """Replace the global connection manager."""
    global _manager
    _manager = manager
    configure_routes(_sessions, _manager)


def get_session_store() -> SessionStore:
    """Return the global session store."""
    return _sessions


def set_session_store(store: SessionStore) -> None:
    """Replace the global session store."""
    global _sessions
    _sessions = store
    configure_routes(_sessions, _manager)


async def _cleanup_stale_sessions() -> None:
    """Periodically remove sessions with no WebSocket connections and no
    activity within the TTL window."""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        try:
            removed = _sessions.remove_stale(
                ttl_seconds=_SESSION_TTL_SECONDS,
                active_sessions=set(_manager.active_sessions()),
            )
            if removed:
                _log.info("Cleaned up %d stale session(s): %s", len(removed), removed)
        except Exception:
            _log.exception("Error during session cleanup")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — startup/shutdown hooks."""
    global _cleanup_task
    _log.info("Autopoiesis server starting")
    _cleanup_task = asyncio.create_task(_cleanup_stale_sessions())
    yield
    _log.info("Autopoiesis server shutting down")
    _cleanup_task.cancel()


app = FastAPI(
    title="Autopoiesis",
    version="0.1.0",
    lifespan=lifespan,
)

configure_routes(_sessions, _manager)
app.include_router(router)
