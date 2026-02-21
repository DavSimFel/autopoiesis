# Autopoiesis PWA — Frontend Shell

Mobile-first Progressive Web App shell for the Autopoiesis agent system.

## Architecture

```
server (MCP/JSON only)
    │
    ├── POST /mcp          → Tool calls (Streamable HTTP / JSON-RPC 2.0)
    └── GET  /mcp/sse      → Push events (Server-Sent Events)
                                │
                            UIEvent { type, data, meta }
                                │
                          Component Registry
                                │
                     ┌──────────┴──────────┐
                     │    Svelte Shell      │
                     │  (owns all rendering)│
                     └─────────────────────┘
```

## Key Principles

- **Server returns JSON only.** No HTML/CSS from server. Shell owns all rendering.
- **Streamable HTTP** for tool calls, **SSE** for push (no WebSockets).
- **CF Access**: `credentials: 'include'` — session cookies, not service tokens.
- **Dark mode only** for v1.
- **Active State**: `resolvable: true` events live in the persistent inbox until explicitly resolved.

## Data Contract

Every server push follows `UIEvent`:

```typescript
interface UIEvent {
  type: string;                    // → component registry key
  data: Record<string, unknown>;   // component props
  meta: {
    id: string;
    mode: 'stream' | 'focus';
    priority: number;              // lower = more urgent
    ephemeral: boolean;
    resolvable: boolean;           // true → lives in Active State until resolved
    badge?: string;
    timestamp: string;
  };
}
```

## Surfaces

| Surface | Description |
|---------|-------------|
| **Stream** | Default feed, all events newest-first |
| **Active State** | Persistent inbox — resolvable unresolved items only. Desktop: right panel. Mobile: slide-over drawer. |
| **Focus** | Full-screen single event view |
| **More** | ALL MCP skills listed alphabetically — the deterministic escape hatch |

## Navigation

- **Mobile**: Bottom tab bar (💬 📋 🏠 🔔 ⋯)
- **Desktop**: Left icon sidebar + right Active State panel

## Component Registry

| Type | Component | Notes |
|------|-----------|-------|
| `agent-status` | `AgentStatus` | Health dot + counts |
| `action-card` | `ActionCard` | Generic action with buttons |
| `approval-item` | `ApprovalItem` | Approve/Reject with countdown |
| `approval-queue` | `ApprovalQueue` | List of approval items |
| `t2-summary` | `T2Summary` | Summary + raw logs toggle |
| `chat-message` | `ChatMessage` | Message bubble (user/assistant/tool) |
| `tool-call` | `ToolCallCard` | Inline tool execution |
| `morning-briefing` | `MorningBriefing` | Composed status card |
| *(unknown)* | `FallbackCard` | Formatted JSON — never crashes |

## Notification Governance

- Max **5 push notifications per day**
- **Quiet hours**: 23:00–08:00 CET
- iOS Home Screen install prompt (Safari only, not yet installed)

## Deployment Topology

```
Browser
  │
  └── autopoiesis.feldhofer.cc   (CF Pages — static SvelteKit)
        │
        ├── GET/POST /mcp/*  →  SvelteKit server proxy route
        │                          │
        │                          └── autopoiesis-api.feldhofer.cc/mcp/*
        │                                (CF Tunnel → localhost:8420)
        │
        └── GET /mcp/sse  →  same proxy, SSE stream passed through
```

**Why proxy?** Same-origin calls eliminate CORS entirely. CF Access cookies
are forwarded server-side by the proxy. EventSource (SSE) works without
custom headers.

## Development

```bash
cp .env.example .env
# Edit .env — MCP_API_URL and VITE_ overrides if needed

npm install
npm run dev
```

## Production Build (Cloudflare Pages)

```bash
npm run build
# Output: .svelte-kit/cloudflare/

npx wrangler pages deploy .svelte-kit/cloudflare
```

The `@sveltejs/adapter-cloudflare` produces a CF Pages Functions bundle.
Server routes (proxy) run as edge Workers.

## Environment Variables

| Variable | Where | Default | Description |
|----------|-------|---------|-------------|
| `MCP_API_URL` | Server (private) | `https://autopoiesis-api.feldhofer.cc` | MCP API upstream for proxy |
| `VITE_MCP_BASE_URL` | Client (browser) | `/mcp` | MCP endpoint from browser — usually same-origin via proxy |
| `VITE_SSE_ENDPOINT` | Client (browser) | `/mcp/sse` | SSE push endpoint |

Set via `wrangler.toml` `[vars]` for non-secrets, or `wrangler secret put` for secrets.
