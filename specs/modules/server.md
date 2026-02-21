# Module: server

## Purpose

FastAPI-based HTTP and WebSocket server providing a REST and real-time API
for agent interactions, with session management, authentication, and
streaming support. Also exposes a FastMCP 3.0 Streamable HTTP endpoint for
Model Context Protocol tool access.

## Status

- **Last updated:** 2026-02-21 (Issue #221)
- **Source:** `src/autopoiesis/server/`

## Key Concepts

- **SessionStore** — Thread-safe in-memory session manager tracking metadata and serialized message history
- **ConnectionManager** — Async WebSocket connection tracker supporting multi-device per-session broadcast
- **WebSocketStreamHandle** — Streams agent output over WebSocket to all connected session clients
- **API key auth** — Optional `X-API-Key` header verification for REST and WebSocket endpoints
- **FastMCP endpoint** — Streamable HTTP MCP server at `/mcp` exposing runtime controls as MCP tools

## Architecture

| File | Responsibility |
|------|---------------|
| `server/app.py` | FastAPI application with REST and WebSocket endpoints, lifespan; mounts `/mcp` via FastMCP |
| `server/cli.py` | `serve` subcommand entry point, uvicorn launcher |
| `server/models.py` | Pydantic request/response models (`ChatRequest`, `ChatResponse`, `WSIncoming`, `WSOutgoing`, `SessionInfo`, etc.) |
| `server/sessions.py` | In-memory `SessionStore` with thread-safe session CRUD and history |
| `server/connections.py` | `ConnectionManager` for WebSocket lifecycle and broadcast |
| `server/stream_handle.py` | `WebSocketStreamHandle` bridging agent streaming to WebSocket clients |
| `server/auth.py` | API key verification for HTTP and WebSocket |
| `server/routes.py` | REST/WebSocket route handlers and runtime error mapping |
| `server/mcp_server.py` | FastMCP server factory, MCP tool handlers, approval notification dispatch |
| `server/mcp_tools.py` | Private data-layer helpers for MCP tools: JSON envelope helpers, approval DB access, pending-approval queries |
| `server/api_routes.py` | REST API router wrapping MCP tools as `/api/*` endpoints for PWA consumption |

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

### MCP Endpoint (`/mcp`)

FastMCP 3.0 Streamable HTTP endpoint mounted at `/mcp`. Available when the
`fastmcp` package is installed. Exposes the following tools:

| Tool | Description |
|------|-------------|
| `dashboard.status` | Runtime health: agent name, shell tier, unlock status, pending approval count |
| `approval.list` | List all pending approval envelopes with tool call details |
| `approval.decide` | Approve or reject a pending envelope by `envelope_id` or `nonce` |
| `system.info` | Runtime version, uptime, and loaded agent configuration summaries |

All MCP tools return JSON-encoded envelopes with `type`, `data`, and `meta`
fields. If the runtime is not initialized, tools return an
`error.runtime_uninitialized` envelope instead of raising.

## Dependencies

- `fastapi`
- `uvicorn`
- `pydantic-ai-slim` (for message types)
- `fastmcp` (optional, required for `/mcp` endpoint)

## Change Log

- 2026-02-16: Initial server module (#126)
- 2026-02-17: Paths updated for `src/autopoiesis/` layout (#152)
- 2026-02-18: Deferred approvals are now explicitly unsupported in serve mode:
  `/api/chat` returns 409, WebSocket emits `approval_unsupported`, and approve
  operations no longer acknowledge placeholders. (Issue #170)
- 2026-02-21: Added FastMCP 3.0 Streamable HTTP endpoint at `/mcp` with
  `dashboard.status`, `approval.list`, `approval.decide`, and `system.info`
  tools. MCP helpers split into `mcp_server.py` (server factory + handlers)
  and `mcp_tools.py` (data-layer helpers). (Issue #221)
- 2026-02-21: Added `api_routes.py` REST API router exposing MCP tool calls
  as `/api/*` JSON endpoints for PWA front-end consumption. (Issue #221 Phase 2)
