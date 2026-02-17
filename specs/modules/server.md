# Module: server

## Purpose

FastAPI-based HTTP and WebSocket server providing a REST and real-time API
for agent interactions, with session management, authentication, and
streaming support.

## Status

- **Last updated:** 2026-02-16 (PR #126)
- **Source:** `server/`

## Key Concepts

- **SessionStore** — Thread-safe in-memory session manager tracking metadata and serialized message history
- **ConnectionManager** — Async WebSocket connection tracker supporting multi-device per-session broadcast
- **WebSocketStreamHandle** — Streams agent output over WebSocket to all connected session clients
- **API key auth** — Optional `X-API-Key` header verification for REST and WebSocket endpoints

## Architecture

| File | Responsibility |
|------|---------------|
| `server/app.py` | FastAPI application with REST and WebSocket endpoints, lifespan |
| `server/cli.py` | `serve` subcommand entry point, uvicorn launcher |
| `server/models.py` | Pydantic request/response models (`ChatRequest`, `ChatResponse`, `WSIncoming`, `WSOutgoing`, `SessionInfo`, etc.) |
| `server/sessions.py` | In-memory `SessionStore` with thread-safe session CRUD and history |
| `server/connections.py` | `ConnectionManager` for WebSocket lifecycle and broadcast |
| `server/stream_handle.py` | `WebSocketStreamHandle` bridging agent streaming to WebSocket clients |
| `server/auth.py` | API key verification for HTTP and WebSocket |

## API Surface

### REST Endpoints

- `GET /api/health` — Health check
- `POST /api/chat` — Send a message, receive agent response
- `GET /api/sessions` — List sessions
- `POST /api/sessions` — Create a session
- `GET /api/sessions/{id}/history` — Retrieve session message history

### WebSocket

- `WS /api/ws/{session_id}` — Real-time bidirectional agent interaction

### Environment Variables

| Var | Required | Default | Notes |
|-----|----------|---------|-------|
| `AUTOPOIESIS_HOST` | No | `127.0.0.1` | Server bind address |
| `AUTOPOIESIS_PORT` | No | `8420` | Server bind port |
| `AUTOPOIESIS_API_KEY` | No | — | When set, enables API key auth |

### CLI

```
autopoiesis serve [--host HOST] [--port PORT]
```

## Dependencies

- `fastapi`
- `uvicorn`
- `pydantic-ai-slim` (for message types)

## Change Log

- 2026-02-16: Initial server module (#126)

- 2026-02-17: Paths updated for `src/autopoiesis/` layout (#152)
