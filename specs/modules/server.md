# Module: server

## Purpose

FastAPI-based HTTP and WebSocket server providing a REST and real-time API
for agent interactions, with session management, authentication, and
streaming support.

## Status

- **Last updated:** 2026-02-18 (Issue #170)
- **Source:** `src/autopoiesis/server/`

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
| `server/routes.py` | REST/WebSocket route handlers and runtime error mapping |

## API Surface

### REST Endpoints

- `GET /api/health` — Health check
- `POST /api/chat` — Send a message, receive agent response
- `GET /api/sessions` — List sessions
- `POST /api/sessions` — Create a session
- `GET /api/sessions/{id}/history` — Retrieve session message history

### WebSocket

- `WS /api/ws/{session_id}` — Real-time bidirectional agent interaction
- `op="message"` with deferred output emits `WSOutgoing(op="error", data={"code":"approval_unsupported", ...})`
- `op="approve"` currently returns the same unsupported error payload

## Deferred Approval Behavior

Serve mode does not implement signed deferred approval submission yet.

- `POST /api/chat` returns `409` with
  `detail={"code":"approval_unsupported","message":"Deferred approvals are not supported in server mode yet."}`
  when agent output contains deferred tool requests.
- WebSocket message handling emits `op="error"` with the same code/message
  instead of an `approval_request` event.
- Worker locked-deferred errors are caught via typed `DeferredApprovalLockedError`
  exception (replacing string-matching heuristic) and normalized to the same
  unsupported response.

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
- 2026-02-18: Deferred approvals are now explicitly unsupported in serve mode:
  `/api/chat` returns 409, WebSocket emits `approval_unsupported`, and approve
  operations no longer acknowledge placeholders. (Issue #170)
