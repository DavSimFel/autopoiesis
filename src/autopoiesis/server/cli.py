"""Server CLI entry point — ``autopoiesis serve``."""

from __future__ import annotations

import os


def run_server(host: str | None = None, port: int | None = None) -> None:
    """Start the FastAPI server with uvicorn."""
    import uvicorn

    resolved_host = host or os.getenv("AUTOPOIESIS_HOST", "127.0.0.1")
    resolved_port = port or int(os.getenv("AUTOPOIESIS_PORT", "8420"))

    uvicorn.run(
        "autopoiesis.server.app:app",
        host=resolved_host,
        port=resolved_port,
        log_level="info",
    )
