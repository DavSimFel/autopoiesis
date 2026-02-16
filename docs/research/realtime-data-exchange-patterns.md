# Real-Time Data Exchange Patterns for the AI Agent Workbench

**Date:** 2026-02-16  
**Context:** FastAPI backend ↔ SvelteKit PWA frontend for Silas (AI agent workbench)  
**TL;DR:** Use a single multiplexed WebSocket with topic-based pub/sub, JSON wire format, sequence-number-based reconnection, and Pydantic→TypeScript type generation. This is what Discord, Linear, and Slack all converge on.

---

## Table of Contents

1. [The Recommendation (Up Front)](#1-the-recommendation)
2. [Data Exchange Pattern Comparison](#2-data-exchange-pattern-comparison)
3. [Why WebSocket + REST Hybrid Wins](#3-why-websocket--rest-hybrid-wins)
4. [Protocol Design](#4-protocol-design)
5. [Subscription System](#5-subscription-system)
6. [State Synchronization](#6-state-synchronization)
7. [Per-Panel Analysis](#7-per-panel-analysis)
8. [FastAPI Implementation](#8-fastapi-implementation)
9. [SvelteKit Client Implementation](#9-sveltekit-client-implementation)
10. [Type Sharing Strategy](#10-type-sharing-strategy)
11. [What Production Systems Actually Do](#11-what-production-systems-actually-do)
12. [Build Order](#12-build-order)

---

## 1. The Recommendation

**Pattern:** Single multiplexed WebSocket for all real-time data + REST for CRUD operations  
**Wire format:** JSON (not MessagePack, not Protobuf)  
**Subscription model:** Topic-based pub/sub with sequence numbers  
**Reconnection:** Sequence-number-based resume (Linear/Discord pattern)  
**Type sharing:** Pydantic models → generated TypeScript types  
**Server library:** Raw Starlette WebSocket (no Socket.IO, no third-party abstraction)  
**Client library:** Custom WebSocket manager class with Svelte 5 runes  

**Why this specific combination:**
- It's what Discord (hundreds of millions of concurrent connections) and Linear (real-time project management) both use
- JSON is debuggable, universal, and fast enough — our bottleneck is LLM token generation, not serialization
- A single connection avoids connection-limit issues and simplifies auth
- Topic-based pub/sub maps perfectly to our panel model (each panel = subscription topics)
- Raw WebSocket gives full control without framework lock-in; Socket.IO adds overhead we don't need for a single-user system
- Sequence numbers make reconnection deterministic and simple

---

## 2. Data Exchange Pattern Comparison

### WebSocket (Bidirectional) ✅ CHOSEN

| Aspect | Rating |
|--------|--------|
| Latency | **Excellent** — persistent TCP connection, no HTTP overhead per message |
| Complexity | **Medium** — need to build protocol, manage connections, handle reconnection |
| Scalability | **Excellent** — single connection per client handles unlimited message types |
| Reconnection | **Manual** — must implement resume/replay logic |
| State sync | **Manual** — must implement snapshot+delta pattern |
| Typing | **Manual** — define message schemas, generate types |
| Ecosystem | **Excellent** — native browser API, Starlette built-in support |

**Verdict:** The right choice for a workbench with 8+ simultaneous real-time panels. One connection, full control.

### Server-Sent Events (SSE)

| Aspect | Rating |
|--------|--------|
| Latency | **Good** — persistent HTTP connection, slightly more overhead than WS |
| Complexity | **Low** — simple text protocol, built-in auto-reconnect with `Last-Event-ID` |
| Scalability | **Limited** — unidirectional (server→client only), need separate channel for client→server |
| Reconnection | **Built-in** — browser auto-reconnects, `Last-Event-ID` header for resume |
| Typing | **Manual** |
| Ecosystem | **Good** — `EventSource` API, FastAPI `StreamingResponse` |

**Verdict:** Great for simpler apps. The unidirectional limitation is a dealbreaker — our workbench needs client→server messages (steering sub-agents, approvals, terminal input). You'd end up needing SSE + REST POST, which is strictly worse than a single WebSocket.

### GraphQL Subscriptions

| Aspect | Rating |
|--------|--------|
| Latency | **Good** — typically runs over WebSocket anyway |
| Complexity | **High** — needs GraphQL server (Strawberry/Ariadne), schema definition, subscription resolvers |
| Scalability | **Good** — well-defined subscription semantics |
| Reconnection | **Framework-dependent** — Apollo Client handles this |
| Typing | **Excellent** — schema-first, codegen for TypeScript types |
| Ecosystem | **Medium for Python** — Strawberry is good but adds a layer; Apollo Client is excellent on frontend |

**Verdict:** Excellent typing story, but adds a massive architectural layer (GraphQL server) for a single-user app. The schema overhead isn't worth it when we can achieve the same type safety with Pydantic + codegen. Linear uses GraphQL for mutations but uses a custom sync protocol over WebSocket for real-time — they don't even use GraphQL subscriptions for their real-time data.

### tRPC Subscriptions

| Aspect | Rating |
|--------|--------|
| Latency | **Good** |
| Complexity | **Medium** — but requires Node.js server (tRPC is TypeScript-native) |
| Typing | **Excellent** — end-to-end type inference |
| Ecosystem | **N/A for Python** — tRPC is a TypeScript ecosystem tool |

**Verdict:** Not viable. Our backend is Python/FastAPI. tRPC requires a Node.js server.

### CRDT-based Sync (Yjs, Automerge)

| Aspect | Rating |
|--------|--------|
| Latency | **Excellent** — local-first, instant mutations |
| Complexity | **Very High** — need to model all data as CRDTs, handle garbage collection, manage document lifecycle |
| Scalability | **Excellent for collaboration** — designed for multi-user conflict resolution |
| Reconnection | **Built-in** — CRDTs merge automatically |
| Typing | **Poor** — CRDT libraries have their own type systems that don't map cleanly to Pydantic |
| Ecosystem | **Growing** — Yjs is mature, but integrating with a Python backend is rough |

**Verdict:** Massively overkill. CRDTs solve multi-user conflict resolution. We have one user and one agent. The agent is authoritative for its outputs, the user is authoritative for their inputs. There are no conflicts to resolve. Figma uses CRDTs because 10 designers edit the same canvas simultaneously — that's not our problem.

### Event Sourcing / Event Bus

| Aspect | Rating |
|--------|--------|
| Latency | **Good** |
| Complexity | **High** — event store, projections, replay logic |
| Scalability | **Excellent** — replay any time range, build any view |
| Reconnection | **Excellent** — replay from last known sequence number |

**Verdict:** The *concept* of event sourcing (sequence-numbered events, replay on reconnect) is exactly right. But a full event sourcing framework (EventStoreDB, Kafka) is overkill. We take the pattern, not the infrastructure. This is what Discord and Linear both do — they have sequence-numbered events but don't use formal event sourcing infrastructure.

### Phoenix Channels / LiveView Pattern

| Aspect | Rating |
|--------|--------|
| Concept | **Excellent** — topic-based pub/sub over WebSocket, presence tracking, automatic diff-based DOM updates |
| Applicability | **Conceptual only** — Elixir/Erlang ecosystem |

**Verdict:** Phoenix Channels are the gold standard for real-time. We steal the design (topic-based multiplexing, join/leave semantics, presence) and implement it in Python. LiveView's server-rendered approach doesn't apply since we want a rich SvelteKit frontend.

### Supabase Realtime Pattern

| Aspect | Rating |
|--------|--------|
| Concept | **Good** — Postgres WAL → WebSocket → client |
| Applicability | **Limited** — tightly coupled to Postgres CDC; our data comes from the agent runtime, not from DB changes |

**Verdict:** Wrong abstraction level. Most of our real-time data (streaming tokens, terminal output, sub-agent status) doesn't originate from database changes. It comes from the async agent loop. Postgres CDC would only cover a fraction of our needs.

---

## 3. Why WebSocket + REST Hybrid Wins

The pattern that every major real-time app converges on:

- **WebSocket** for: server-pushed events, streaming data, real-time state changes
- **REST** for: initial page load, CRUD operations, file uploads, one-off queries

**Why not WebSocket for everything?**
- REST is stateless and cacheable — great for initial data loads
- REST has better tooling (OpenAPI docs, curl, Postman)
- REST operations don't need connection state
- File uploads are awkward over WebSocket
- HTTP middleware (auth, rate limiting) is more mature

**Why not REST for everything?**
- Polling is wasteful and adds latency
- Long-polling is a hack
- SSE is unidirectional
- You can't stream 100 tokens/sec over HTTP without a persistent connection

**The split:**

| Operation | Protocol | Why |
|-----------|----------|-----|
| Load conversation history | REST GET | One-time fetch, cacheable |
| Send message | REST POST | Simple request-response, idempotent with request ID |
| Stream AI response tokens | WebSocket | High-frequency server push |
| Approve/deny action | REST POST (+ WS notification) | CRUD with confirmation |
| Sub-agent status updates | WebSocket | Continuous server push |
| File browser updates | WebSocket | Event-driven server push |
| Terminal output | WebSocket | High-frequency byte stream |
| Upload file | REST POST multipart | Binary data transfer |
| Update settings | REST PUT | Simple CRUD |

---

## 4. Protocol Design

### Message Envelope

Every WebSocket message follows a single envelope format (inspired by Discord's Gateway protocol):

```typescript
// Client → Server
interface ClientMessage {
  op: number;       // Operation code
  d: unknown;       // Payload data
  seq?: number;     // Client sequence (for ACKs)
  ref?: string;     // Request reference (for request-response over WS)
}

// Server → Client
interface ServerMessage {
  op: number;       // Operation code  
  t?: string;       // Event type (for dispatch events)
  d: unknown;       // Payload data
  seq: number;      // Server sequence number (monotonically increasing)
  ref?: string;     // Echoed request reference
}
```

### Operation Codes

```typescript
enum OpCode {
  // Server → Client
  DISPATCH    = 0,  // Event dispatch (carries t + d)
  HEARTBEAT   = 1,  // Heartbeat request
  HELLO       = 2,  // Initial connection payload (heartbeat interval, server info)
  ACK         = 3,  // Heartbeat acknowledgement
  ERROR       = 4,  // Error response
  
  // Client → Server
  IDENTIFY    = 10, // Auth + subscribe to initial topics
  HEARTBEAT   = 11, // Heartbeat response
  SUBSCRIBE   = 12, // Subscribe to topics
  UNSUBSCRIBE = 13, // Unsubscribe from topics
  RESUME      = 14, // Resume with last sequence number
  COMMAND     = 15, // Client command (steering, approval, terminal input)
}
```

### Event Types (t field on DISPATCH)

```typescript
// Chat
"chat.token"           // Streaming token
"chat.message"         // Complete message (user or assistant)
"chat.tool_call"       // Tool call started
"chat.tool_result"     // Tool call completed
"chat.approval"        // Approval request
"chat.error"           // Generation error

// Sub-agents
"agent.started"        // Sub-agent spawned
"agent.progress"       // Status/log update  
"agent.completed"      // Sub-agent finished
"agent.failed"         // Sub-agent failed

// Files
"file.created"         // New file
"file.modified"        // File changed
"file.deleted"         // File removed

// Terminal
"terminal.output"      // stdout/stderr chunk
"terminal.exit"        // Process exited

// Tasks
"task.created"         // New task
"task.updated"         // Task status change
"task.completed"       // Task done

// Session
"session.created"      // New session
"session.updated"      // Session state change

// Notifications
"notification.new"     // New notification

// System
"system.status"        // System health update
"system.cost"          // Cost tracking update
```

### Example Message Flow

```
Client                          Server
  |                                |
  |-------- [WS Connect] -------->|
  |                                |
  |<------- HELLO (op:2) ---------|  {"heartbeat_interval": 30000, "server_version": "0.2.0"}
  |                                |
  |-------- IDENTIFY (op:10) ---->|  {"token": "xxx", "topics": ["chat:session-1", "agents:*", "files:workspace"]}
  |                                |
  |<------- DISPATCH (op:0) ------|  seq:1, t:"session.state", d:{messages: [...], agents: [...]}  (initial snapshot)
  |                                |
  |<------- DISPATCH (op:0) ------|  seq:2, t:"chat.token", d:{session_id: "s1", token: "Hello"}
  |<------- DISPATCH (op:0) ------|  seq:3, t:"chat.token", d:{session_id: "s1", token: " world"}
  |                                |
  |-------- COMMAND (op:15) ----->|  {"type": "approve", "approval_id": "a1", "decision": "allow"}
  |                                |
  |<------- DISPATCH (op:0) ------|  seq:4, t:"chat.tool_call", d:{...}
  |                                |
  |-------- HEARTBEAT (op:11) --->|
  |<------- ACK (op:3) ----------|
  |                                |
  |======= [CONNECTION DROPS] ====|
  |                                |
  |-------- [WS Reconnect] ------>|
  |<------- HELLO (op:2) ---------|
  |-------- RESUME (op:14) ------>|  {"token": "xxx", "last_seq": 4}
  |<------- DISPATCH (op:0) ------|  seq:5, t:"chat.token", d:{...}   (missed events replayed)
  |<------- DISPATCH (op:0) ------|  seq:6, t:"chat.token", d:{...}
  |                                |  (continues from where it left off)
```

---

## 5. Subscription System

### Topic-Based Pub/Sub

Topics follow a hierarchical namespace:

```
chat:{session_id}          # All events for a chat session
chat:{session_id}:tokens   # Only streaming tokens (fine-grained)
agents:*                   # All sub-agent events
agents:{agent_id}          # Specific sub-agent
files:{workspace}          # File system events for a workspace
terminal:{process_id}      # Terminal output for a process
tasks:*                    # All task events
notifications:{user_id}   # User notifications
system:status              # System health
system:cost                # Cost tracking
```

### Subscription Lifecycle

```python
# Client subscribes on IDENTIFY (initial topics)
# Client can add/remove subscriptions dynamically:

# Subscribe
{"op": 12, "d": {"topics": ["terminal:proc-abc123"]}}

# Unsubscribe  
{"op": 13, "d": {"topics": ["terminal:proc-abc123"]}}
```

### Snapshot + Delta Pattern

This is the critical design decision. When a client subscribes to a topic, it needs:
1. **Current state** (snapshot) — what does the world look like right now?
2. **Subsequent changes** (deltas) — what changes from this point forward?

**Implementation:**

```python
# On IDENTIFY or SUBSCRIBE, server sends:
# 1. A snapshot event with current state
# 2. All subsequent deltas

# Example: subscribing to chat:session-1
# Server sends:
{
  "op": 0, "seq": 100, "t": "chat.snapshot",
  "d": {
    "session_id": "session-1",
    "messages": [...],  # All existing messages
    "pending_approvals": [...],
    "active_generation": null  # Or current partial message if mid-stream
  }
}
# Then continues with deltas:
{"op": 0, "seq": 101, "t": "chat.token", "d": {...}}
```

### Multiplexing

All subscriptions share a single WebSocket connection. The server maintains a per-connection subscription set. Each dispatched event includes enough context (session_id, agent_id, etc.) for the client to route it to the correct store/panel.

**No per-topic connections.** One WebSocket handles everything. The server filters events based on the client's subscription set before sending.

### Backpressure

For high-frequency streams (tokens, terminal output):
- **Server-side batching:** Accumulate tokens/bytes for up to 16ms, send as a batch. This turns 100 individual messages/sec into ~60 batched messages/sec without perceptible latency.
- **Client-side:** If the WebSocket buffer exceeds a threshold, the server can drop non-critical events (e.g., intermediate progress updates) and send a "resync" event.

### Ordering Guarantees

The global sequence number (`seq`) provides total ordering. Within a topic, events are always delivered in order. Across topics, events are delivered in seq order (which matches real-world causality since the server assigns seq numbers in processing order).

---

## 6. State Synchronization

### Reconnection Strategy

**Discord/Linear hybrid approach:**

1. Client caches `last_seq` (last received sequence number)
2. Server maintains a **replay buffer** — last N events (e.g., last 1000 events or last 5 minutes)
3. On reconnect, client sends `RESUME` with `last_seq`
4. Server replays all events with `seq > last_seq` from the buffer
5. If `last_seq` is too old (not in buffer), server sends `INVALID_SESSION` → client does a full resync (re-IDENTIFY, get fresh snapshots)

```python
# Server-side replay buffer (simple in-memory ring buffer)
class ReplayBuffer:
    def __init__(self, max_size: int = 5000):
        self.buffer: deque[ServerMessage] = deque(maxlen=max_size)
        self.seq_counter: int = 0
    
    def append(self, event: ServerMessage) -> int:
        self.seq_counter += 1
        event.seq = self.seq_counter
        self.buffer.append(event)
        return self.seq_counter
    
    def replay_from(self, last_seq: int) -> list[ServerMessage] | None:
        """Return events after last_seq, or None if too old."""
        if not self.buffer or last_seq < self.buffer[0].seq - 1:
            return None  # Too old, need full resync
        return [e for e in self.buffer if e.seq > last_seq]
```

### Optimistic Updates

For user-initiated actions (send message, approve action):

1. Client generates a `ref` (request reference ID, e.g., UUID)
2. Client immediately updates local UI (optimistic)
3. Client sends the action via REST POST (not WebSocket — REST gives proper HTTP status codes and is idempotent)
4. Server processes and broadcasts the result via WebSocket with the same `ref`
5. Client reconciles: if `ref` matches, update the optimistic entry; if error, rollback

```typescript
// Client sends message
const ref = crypto.randomUUID();
messages.push({ ref, role: 'user', content: text, status: 'sending' });

const res = await fetch('/api/chat/send', {
  method: 'POST',
  body: JSON.stringify({ ref, session_id, content: text })
});

// When WebSocket delivers the confirmed message:
// { t: "chat.message", d: { ref: "...", id: "msg-123", ... } }
// Client replaces optimistic entry with server-confirmed version
```

### Conflict Resolution

**Last-write-wins for most things.** Here's why:

- **Chat messages:** Append-only. No conflicts possible.
- **Approvals:** Single actor (user approves OR denies). No conflict.
- **Settings/preferences:** User is sole author. Last-write-wins.
- **Files:** Agent writes, user reads (or vice versa). If both edit, the file system's last-write-wins is fine — this is `vim` semantics, not Google Docs.
- **Agent steering:** User commands are authoritative. Agent obeys.

CRDTs and OT are solutions to a problem we don't have. With one user and one agent (which follows instructions), there are no concurrent conflicting edits. If we ever add multi-user support, we can add conflict resolution for specific data types (e.g., shared documents) without changing the transport layer.

---

## 7. Per-Panel Analysis

| Panel | Data Pattern | Update Freq | Transport | Client Store Pattern |
|-------|-------------|-------------|-----------|---------------------|
| **Chat tokens** | Append-only ordered stream | 50-100/sec → batched to ~60/sec | WS `chat.token` events, batched every 16ms | Append to `$state` message array; use `requestAnimationFrame` for DOM updates |
| **Tool calls/results** | Discrete structured events | Bursty (0 or 5-10/sec) | WS `chat.tool_call` / `chat.tool_result` | Insert into message stream at correct position |
| **Sub-agent status** | Finite state machine transitions | Every 1-5 sec | WS `agent.*` events | Map of `agent_id → AgentState`, update on event |
| **File browser** | Tree structure CRUD | Sporadic (~1/sec during agent work) | WS `file.*` events | Reactive tree structure, apply create/modify/delete ops |
| **Terminal output** | Ordered byte stream | High (up to 1000 lines/sec) | WS `terminal.output`, batched every 50ms | Ring buffer (last 10K lines), virtual scroll renderer |
| **Task dashboard** | Aggregate counters + status | Every 2-5 sec | WS `task.*` + `system.cost` events | Derived/computed state from task list |
| **Memory/context** | Document-like, versioned | On change (rare) | WS `memory.*` events or REST poll | Simple replace-on-update |
| **Notifications** | Discrete, prioritized | Sporadic | WS `notification.new` | Append to notification list, sort by priority/time |
| **Session list** | List with status | On creation/update | WS `session.*` events | Simple list with reactive status |

### Batching Strategy

High-frequency streams (tokens, terminal) benefit from server-side batching:

```python
class TokenBatcher:
    """Accumulate tokens and flush every 16ms (one frame at 60fps)."""
    
    def __init__(self, flush_callback, interval_ms: int = 16):
        self.buffer: list[str] = []
        self.flush_callback = flush_callback
        self.interval = interval_ms / 1000
        self._task: asyncio.Task | None = None
    
    def add(self, token: str):
        self.buffer.append(token)
        if self._task is None:
            self._task = asyncio.create_task(self._flush_loop())
    
    async def _flush_loop(self):
        await asyncio.sleep(self.interval)
        tokens = self.buffer
        self.buffer = []
        self._task = None
        if tokens:
            await self.flush_callback(tokens)
```

---

## 8. FastAPI Implementation

### WebSocket Manager

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from collections import deque
from dataclasses import dataclass, field
import asyncio
import json
import time

@dataclass
class ClientConnection:
    ws: WebSocket
    user_id: str
    topics: set[str] = field(default_factory=set)
    last_heartbeat: float = 0
    authenticated: bool = False

class WebSocketManager:
    def __init__(self, replay_buffer_size: int = 5000):
        self.connections: dict[str, ClientConnection] = {}
        self.replay_buffer: deque[dict] = deque(maxlen=replay_buffer_size)
        self.seq: int = 0
        self._lock = asyncio.Lock()
    
    async def connect(self, ws: WebSocket, connection_id: str) -> ClientConnection:
        await ws.accept()
        conn = ClientConnection(ws=ws, user_id="", last_heartbeat=time.time())
        self.connections[connection_id] = conn
        
        # Send HELLO
        await ws.send_json({
            "op": 2,
            "d": {"heartbeat_interval": 30000, "server_version": "0.2.0"},
            "seq": 0
        })
        return conn
    
    def disconnect(self, connection_id: str):
        self.connections.pop(connection_id, None)
    
    async def dispatch(self, event_type: str, data: dict, topics: set[str] | None = None):
        """Dispatch an event to all subscribed connections."""
        async with self._lock:
            self.seq += 1
            msg = {"op": 0, "t": event_type, "d": data, "seq": self.seq}
            self.replay_buffer.append(msg)
        
        for conn in list(self.connections.values()):
            if not conn.authenticated:
                continue
            # Check if connection is subscribed to any matching topic
            if topics and not topics.intersection(conn.topics):
                continue
            try:
                await conn.ws.send_json(msg)
            except Exception:
                pass  # Connection cleanup happens in the receive loop
    
    async def replay(self, connection_id: str, last_seq: int) -> bool:
        """Replay missed events. Returns False if full resync needed."""
        conn = self.connections.get(connection_id)
        if not conn:
            return False
        
        if not self.replay_buffer or last_seq < self.replay_buffer[0]["seq"] - 1:
            return False  # Too old
        
        for msg in self.replay_buffer:
            if msg["seq"] > last_seq:
                topics = self._extract_topics(msg)
                if not topics or topics.intersection(conn.topics):
                    await conn.ws.send_json(msg)
        return True
    
    def _extract_topics(self, msg: dict) -> set[str]:
        """Extract relevant topics from a message for filtering."""
        t = msg.get("t", "")
        d = msg.get("d", {})
        topics = set()
        
        if t.startswith("chat."):
            sid = d.get("session_id")
            if sid:
                topics.add(f"chat:{sid}")
        elif t.startswith("agent."):
            aid = d.get("agent_id")
            topics.add("agents:*")
            if aid:
                topics.add(f"agents:{aid}")
        elif t.startswith("file."):
            topics.add(f"files:workspace")
        elif t.startswith("terminal."):
            pid = d.get("process_id")
            if pid:
                topics.add(f"terminal:{pid}")
        elif t.startswith("task."):
            topics.add("tasks:*")
        elif t.startswith("notification."):
            uid = d.get("user_id")
            if uid:
                topics.add(f"notifications:{uid}")
        
        return topics


# FastAPI integration
app = FastAPI()
manager = WebSocketManager()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    conn_id = str(id(ws))
    conn = await manager.connect(ws, conn_id)
    
    try:
        while True:
            raw = await ws.receive_json()
            op = raw.get("op")
            d = raw.get("d", {})
            
            if op == 10:  # IDENTIFY
                token = d.get("token")
                # Validate token...
                conn.authenticated = True
                conn.user_id = "user-1"  # From token
                conn.topics = set(d.get("topics", []))
                # Send initial snapshots for subscribed topics
                await send_snapshots(conn)
                
            elif op == 11:  # HEARTBEAT
                conn.last_heartbeat = time.time()
                await ws.send_json({"op": 3, "d": None, "seq": manager.seq})
                
            elif op == 12:  # SUBSCRIBE
                conn.topics.update(d.get("topics", []))
                # Send snapshots for newly subscribed topics
                for topic in d.get("topics", []):
                    await send_topic_snapshot(conn, topic)
                    
            elif op == 13:  # UNSUBSCRIBE
                conn.topics -= set(d.get("topics", []))
                
            elif op == 14:  # RESUME
                last_seq = d.get("last_seq", 0)
                conn.authenticated = True
                conn.topics = set(d.get("topics", []))
                if not await manager.replay(conn_id, last_seq):
                    # Full resync needed
                    await ws.send_json({"op": 4, "d": {"code": "INVALID_SESSION"}, "seq": manager.seq})
                    await send_snapshots(conn)
                    
            elif op == 15:  # COMMAND
                await handle_command(conn, d)
                
    except WebSocketDisconnect:
        manager.disconnect(conn_id)


async def send_snapshots(conn: ClientConnection):
    """Send current state snapshots for all subscribed topics."""
    for topic in conn.topics:
        await send_topic_snapshot(conn, topic)

async def send_topic_snapshot(conn: ClientConnection, topic: str):
    """Send snapshot for a single topic."""
    if topic.startswith("chat:"):
        session_id = topic.split(":")[1]
        # Load messages, pending approvals, etc.
        snapshot = await get_chat_snapshot(session_id)
        await conn.ws.send_json({
            "op": 0, "t": "chat.snapshot",
            "d": snapshot, "seq": manager.seq
        })
    elif topic == "agents:*":
        agents = await get_active_agents()
        await conn.ws.send_json({
            "op": 0, "t": "agents.snapshot",
            "d": {"agents": agents}, "seq": manager.seq
        })
    # ... etc for each topic type

async def handle_command(conn: ClientConnection, data: dict):
    """Handle client commands (approvals, steering, terminal input)."""
    cmd_type = data.get("type")
    if cmd_type == "approve":
        await process_approval(data["approval_id"], data["decision"])
    elif cmd_type == "steer_agent":
        await steer_agent(data["agent_id"], data["message"])
    elif cmd_type == "terminal_input":
        await send_terminal_input(data["process_id"], data["input"])
```

### Integration with Agent Loop

The key insight: the agent loop is already async. Publishing events is just calling `manager.dispatch()`:

```python
# In the agent's streaming callback
async def on_token(token: str, session_id: str):
    await manager.dispatch("chat.token", {
        "session_id": session_id,
        "token": token,
        "timestamp": time.time()
    }, topics={f"chat:{session_id}"})

# When a sub-agent status changes
async def on_agent_status(agent_id: str, status: str, detail: str):
    await manager.dispatch("agent.progress", {
        "agent_id": agent_id,
        "status": status,
        "detail": detail
    }, topics={"agents:*", f"agents:{agent_id}"})

# File watcher (using watchfiles or inotify)
async def on_file_change(path: str, change_type: str):
    await manager.dispatch(f"file.{change_type}", {
        "path": path,
        "timestamp": time.time()
    }, topics={"files:workspace"})
```

### Why NOT Socket.IO / fastapi-websocket-pubsub

- **Socket.IO:** Adds a protocol layer (Engine.IO) with its own handshake, packet format, and reconnection logic. Useful for browser compatibility fallbacks (long-polling), but we don't need that — modern browsers all support WebSocket. It also brings a heavy client library (80KB+).
- **fastapi-websocket-pubsub:** Good for simple pub/sub but lacks: custom protocol design, sequence numbers, replay buffer, fine-grained topic filtering. We'd outgrow it in a week.
- **Raw Starlette WebSocket:** Full control, zero overhead, exactly the features we need. The manager code above is ~150 lines — simpler than learning a framework's abstractions.

---

## 9. SvelteKit Client Implementation

### WebSocket Client Class

```typescript
// lib/ws/client.ts

import { getContext, setContext } from 'svelte';

interface WSMessage {
  op: number;
  t?: string;
  d: unknown;
  seq: number;
  ref?: string;
}

type EventHandler = (data: unknown, seq: number) => void;

export class WorkbenchSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private token: string;
  private topics: Set<string>;
  private lastSeq = 0;
  private handlers = new Map<string, Set<EventHandler>>();
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  
  // Reactive connection state (Svelte 5 rune)
  connectionState = $state<'connecting' | 'connected' | 'disconnected' | 'resuming'>('disconnected');

  constructor(url: string, token: string, topics: string[]) {
    this.url = url;
    this.token = token;
    this.topics = new Set(topics);
  }

  connect() {
    this.connectionState = 'connecting';
    this.ws = new WebSocket(this.url);
    
    this.ws.onopen = () => {
      this.reconnectDelay = 1000; // Reset on successful connect
    };

    this.ws.onmessage = (event) => {
      const msg: WSMessage = JSON.parse(event.data);
      this.handleMessage(msg);
    };

    this.ws.onclose = (event) => {
      this.connectionState = 'disconnected';
      this.stopHeartbeat();
      if (event.code !== 1000) { // Not a clean close
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      // onclose will fire after this
    };
  }

  private handleMessage(msg: WSMessage) {
    switch (msg.op) {
      case 2: // HELLO
        const { heartbeat_interval } = msg.d as { heartbeat_interval: number };
        this.startHeartbeat(heartbeat_interval);
        
        if (this.lastSeq > 0) {
          // Resume
          this.connectionState = 'resuming';
          this.send({ op: 14, d: { token: this.token, last_seq: this.lastSeq, topics: [...this.topics] } });
        } else {
          // Fresh identify
          this.send({ op: 10, d: { token: this.token, topics: [...this.topics] } });
        }
        break;

      case 0: // DISPATCH
        this.lastSeq = msg.seq;
        this.connectionState = 'connected';
        const handlers = this.handlers.get(msg.t!);
        if (handlers) {
          for (const handler of handlers) {
            handler(msg.d, msg.seq);
          }
        }
        // Also fire wildcard handlers
        const wildcardHandlers = this.handlers.get('*');
        if (wildcardHandlers) {
          for (const handler of wildcardHandlers) {
            handler({ type: msg.t, data: msg.d }, msg.seq);
          }
        }
        break;

      case 3: // ACK
        // Heartbeat acknowledged
        break;

      case 4: // ERROR
        const { code } = msg.d as { code: string };
        if (code === 'INVALID_SESSION') {
          this.lastSeq = 0; // Force full resync on next event
        }
        break;
    }
  }

  on(eventType: string, handler: EventHandler): () => void {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set());
    }
    this.handlers.get(eventType)!.add(handler);
    return () => this.handlers.get(eventType)?.delete(handler);
  }

  subscribe(topics: string[]) {
    for (const t of topics) this.topics.add(t);
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send({ op: 12, d: { topics } });
    }
  }

  unsubscribe(topics: string[]) {
    for (const t of topics) this.topics.delete(t);
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.send({ op: 13, d: { topics } });
    }
  }

  command(data: Record<string, unknown>) {
    this.send({ op: 15, d: data });
  }

  private send(msg: Partial<WSMessage>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  private startHeartbeat(intervalMs: number) {
    this.stopHeartbeat();
    this.heartbeatInterval = setInterval(() => {
      this.send({ op: 11, d: { seq: this.lastSeq } });
    }, intervalMs);
  }

  private stopHeartbeat() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  private scheduleReconnect() {
    this.reconnectTimeout = setTimeout(() => {
      this.connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
  }

  destroy() {
    this.stopHeartbeat();
    if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout);
    this.ws?.close(1000);
  }
}

// Context helpers for Svelte components
const WS_KEY = Symbol('workbench-socket');

export function setWorkbenchSocket(socket: WorkbenchSocket) {
  setContext(WS_KEY, socket);
}

export function getWorkbenchSocket(): WorkbenchSocket {
  return getContext(WS_KEY);
}
```

### Reactive Stores with Runes

```typescript
// lib/stores/chat.svelte.ts

import type { WorkbenchSocket } from '$lib/ws/client';

export interface Message {
  id: string;
  ref?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  tool_calls?: ToolCall[];
  status: 'sending' | 'streaming' | 'complete' | 'error';
  timestamp: number;
}

export class ChatStore {
  messages = $state<Message[]>([]);
  isStreaming = $state(false);
  pendingApprovals = $state<Approval[]>([]);
  
  private currentStreamMessage: Message | null = null;
  private tokenBuffer: string[] = [];
  private flushScheduled = false;

  constructor(private socket: WorkbenchSocket, private sessionId: string) {
    // Subscribe to chat events
    socket.on('chat.snapshot', (data: any) => {
      this.messages = data.messages;
      this.pendingApprovals = data.pending_approvals ?? [];
    });

    socket.on('chat.token', (data: any) => {
      if (data.session_id !== this.sessionId) return;
      this.handleToken(data.token);
    });

    socket.on('chat.message', (data: any) => {
      if (data.session_id !== this.sessionId) return;
      this.finalizeMessage(data);
    });

    socket.on('chat.tool_call', (data: any) => {
      if (data.session_id !== this.sessionId) return;
      this.addToolCall(data);
    });

    socket.on('chat.approval', (data: any) => {
      if (data.session_id !== this.sessionId) return;
      this.pendingApprovals.push(data);
    });
  }

  private handleToken(token: string) {
    // Buffer tokens and flush on animation frame for smooth rendering
    if (!this.currentStreamMessage) {
      this.currentStreamMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: '',
        status: 'streaming',
        timestamp: Date.now()
      };
      this.messages.push(this.currentStreamMessage);
      this.isStreaming = true;
    }
    
    this.tokenBuffer.push(token);
    
    if (!this.flushScheduled) {
      this.flushScheduled = true;
      requestAnimationFrame(() => {
        if (this.currentStreamMessage) {
          this.currentStreamMessage.content += this.tokenBuffer.join('');
          this.tokenBuffer = [];
        }
        this.flushScheduled = false;
      });
    }
  }

  private finalizeMessage(data: any) {
    if (this.currentStreamMessage) {
      // Flush remaining tokens
      this.currentStreamMessage.content += this.tokenBuffer.join('');
      this.tokenBuffer = [];
      this.currentStreamMessage.id = data.id;
      this.currentStreamMessage.status = 'complete';
      this.currentStreamMessage = null;
      this.isStreaming = false;
    }
    // Also reconcile optimistic user messages by ref
    if (data.ref) {
      const optimistic = this.messages.find(m => m.ref === data.ref);
      if (optimistic) {
        optimistic.id = data.id;
        optimistic.status = 'complete';
      }
    }
  }

  async sendMessage(content: string) {
    const ref = crypto.randomUUID();
    // Optimistic add
    this.messages.push({
      id: ref,
      ref,
      role: 'user',
      content,
      status: 'sending',
      timestamp: Date.now()
    });
    
    // Send via REST (not WS) for proper HTTP semantics
    const res = await fetch(`/api/chat/${this.sessionId}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ref, content })
    });
    
    if (!res.ok) {
      const msg = this.messages.find(m => m.ref === ref);
      if (msg) msg.status = 'error';
    }
  }

  approve(approvalId: string, decision: 'allow' | 'deny' | 'edit', edits?: any) {
    this.socket.command({ type: 'approve', approval_id: approvalId, decision, edits });
    this.pendingApprovals = this.pendingApprovals.filter(a => a.id !== approvalId);
  }
}
```

### Connection Status UX

```svelte
<!-- components/ConnectionStatus.svelte -->
<script lang="ts">
  import { getWorkbenchSocket } from '$lib/ws/client';
  
  const socket = getWorkbenchSocket();
</script>

{#if socket.connectionState === 'disconnected'}
  <div class="fixed bottom-4 left-1/2 -translate-x-1/2 bg-red-500/90 text-white px-4 py-2 rounded-lg text-sm flex items-center gap-2 z-50">
    <span class="w-2 h-2 rounded-full bg-white animate-pulse"></span>
    Reconnecting...
  </div>
{:else if socket.connectionState === 'resuming'}
  <div class="fixed bottom-4 left-1/2 -translate-x-1/2 bg-amber-500/90 text-white px-4 py-2 rounded-lg text-sm flex items-center gap-2 z-50">
    <span class="w-2 h-2 rounded-full bg-white animate-pulse"></span>
    Syncing...
  </div>
{/if}
```

### High-Frequency Terminal Output

```typescript
// lib/stores/terminal.svelte.ts

export class TerminalStore {
  lines = $state<string[]>([]);
  private maxLines = 10000;
  private lineBuffer: string[] = [];
  private flushScheduled = false;

  constructor(private socket: WorkbenchSocket, processId: string) {
    socket.subscribe([`terminal:${processId}`]);
    
    socket.on('terminal.output', (data: any) => {
      if (data.process_id !== processId) return;
      // Buffer and flush at 60fps
      this.lineBuffer.push(...data.lines);
      if (!this.flushScheduled) {
        this.flushScheduled = true;
        requestAnimationFrame(() => {
          this.lines = [...this.lines, ...this.lineBuffer].slice(-this.maxLines);
          this.lineBuffer = [];
          this.flushScheduled = false;
        });
      }
    });

    socket.on('terminal.exit', (data: any) => {
      if (data.process_id !== processId) return;
      this.lines.push(`\n[Process exited with code ${data.exit_code}]`);
    });
  }

  sendInput(input: string) {
    this.socket.command({ type: 'terminal_input', process_id: this.processId, input });
  }

  destroy() {
    this.socket.unsubscribe([`terminal:${this.processId}`]);
  }
}
```

---

## 10. Type Sharing Strategy

### Pydantic → TypeScript Generation

Use **pydantic-to-typescript2** or a custom script that converts Pydantic models to TypeScript interfaces:

```python
# shared/events.py — Single source of truth

from pydantic import BaseModel
from typing import Literal
from datetime import datetime

class ChatToken(BaseModel):
    session_id: str
    token: str
    timestamp: float

class ChatMessage(BaseModel):
    id: str
    ref: str | None = None
    session_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    tool_calls: list["ToolCall"] | None = None
    timestamp: datetime

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict
    result: str | None = None
    status: Literal["pending", "running", "complete", "error"]

class AgentStatus(BaseModel):
    agent_id: str
    label: str
    status: Literal["starting", "running", "completed", "failed"]
    detail: str | None = None
    progress: float | None = None

class FileEvent(BaseModel):
    path: str
    change_type: Literal["created", "modified", "deleted"]
    timestamp: float

class ApprovalRequest(BaseModel):
    id: str
    session_id: str
    action: str
    description: str
    risk_level: Literal["low", "medium", "high"]
    details: dict
    
# Event type registry
EVENT_TYPES = {
    "chat.token": ChatToken,
    "chat.message": ChatMessage,
    "chat.tool_call": ToolCall,
    "chat.approval": ApprovalRequest,
    "agent.progress": AgentStatus,
    "file.created": FileEvent,
    "file.modified": FileEvent,
    "file.deleted": FileEvent,
}
```

**Generation script:**

```bash
# scripts/generate-types.sh
pydantic2ts --module shared.events --output frontend/src/lib/types/events.ts
```

This produces:

```typescript
// Auto-generated from shared/events.py — DO NOT EDIT
export interface ChatToken {
  session_id: string;
  token: string;
  timestamp: number;
}

export interface ChatMessage {
  id: string;
  ref?: string | null;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  tool_calls?: ToolCall[] | null;
  timestamp: string; // ISO datetime
}
// ... etc
```

**Why not Protobuf or MessagePack?**
- JSON is human-readable and debuggable in browser DevTools
- Our messages are small (even batched tokens are <1KB)
- The bottleneck is LLM generation speed, not serialization
- JSON.parse is optimized to hell in V8
- Protobuf/MessagePack add schema complexity and build steps for negligible gain at our scale

---

## 11. What Production Systems Actually Do

### Discord Gateway

- **Transport:** Single WebSocket per client
- **Protocol:** JSON or ETF with opcodes (0=Dispatch, 1=Heartbeat, 2=Identify, 6=Resume, 7=Reconnect, 9=Invalid Session, 10=Hello, 11=Heartbeat ACK)
- **State sync:** Sequence numbers (`s` field). Resume with `session_id` + `last_s`. If too old → full reconnect with new IDENTIFY
- **Heartbeat:** Server sends interval in HELLO, client must heartbeat or gets disconnected
- **Sharding:** For bots with many guilds. Not relevant for us.
- **Key lesson:** The opcode + sequence number pattern is battle-tested at enormous scale

### Linear Sync Engine

- **Transport:** WebSocket for real-time sync, GraphQL for mutations
- **Protocol:** Custom sync protocol with `SyncAction` objects (id, action, modelName, modelId, data)
- **State sync:** Monotonically increasing `syncId`. On reconnect, request all SyncActions since `lastSyncId`. If too old → full bootstrap
- **Bootstrap:** Two-phase — full bootstrap (critical models) then partial bootstrap (comments, history)
- **Client storage:** IndexedDB for offline. All data mirrored locally
- **Key lesson:** The snapshot + delta pattern with numeric sequence IDs is the right approach. Two-phase bootstrap is smart for large datasets.

### Figma Multiplayer

- **Transport:** WebSocket
- **Sync model:** NOT full CRDTs. Server is authoritative. Client sends operations, server applies and broadcasts. Custom conflict resolution inspired by OT (not pure OT or CRDT)
- **Key lesson:** Even Figma, the poster child for "real-time collaboration," doesn't use full CRDTs. They use a server-authoritative model with last-writer-wins for most properties. CRDTs are for text editing scenarios (which we don't have).

### Slack Real-Time Messaging

- **Transport:** WebSocket (RTM API, now deprecated in favor of Events API + Socket Mode)
- **Pattern:** Event-driven, each event has a type field and payload
- **Key lesson:** Slack moved AWAY from direct WebSocket to a higher-level Socket Mode (which is WebSocket under the hood but with their SDK). For our single-user case, raw WebSocket is fine.

### Cursor/Windsurf (AI Coding Agents)

- **Streaming:** SSE for token streaming from LLM providers, displayed via custom streaming UI
- **File changes:** File watcher → UI update
- **Terminal:** PTY output streamed to embedded terminal component
- **Key lesson:** These tools don't need complex sync — they're single-user, single-session. Their streaming UX is excellent though.

### Vercel (Deployment Logs)

- **Transport:** WebSocket for log streaming
- **Pattern:** Simple append-only log stream, auto-reconnect
- **Key lesson:** For append-only streams (logs, tokens), the simplest approach works best. No need for conflict resolution.

### Notion

- **Transport:** WebSocket for presence and real-time edits
- **Sync model:** Operation-based — client sends operations, server resolves and broadcasts
- **Key lesson:** Complex collaboration sync is overkill for us. But their block-based content model is relevant for how we might structure memory/context display.

---

## 12. Build Order

### MVP (Week 1-2): Single WebSocket + Chat Streaming

Build the core WebSocket infrastructure and prove it works with the highest-frequency use case (token streaming):

1. **Server:** `WebSocketManager` class with connect/disconnect/dispatch
2. **Server:** HELLO → IDENTIFY handshake
3. **Server:** Token streaming from agent loop → dispatch to connected clients
4. **Client:** `WorkbenchSocket` class with connect, reconnect, event handling
5. **Client:** `ChatStore` with token buffering and `requestAnimationFrame` batching
6. **Client:** Basic connection status indicator

**Test:** Open the workbench, start a conversation, see tokens stream in real-time. Close and reopen the tab — reconnection works.

### Phase 2 (Week 3-4): Full Protocol + Multiple Panels

1. **Server:** Replay buffer + RESUME support
2. **Server:** Topic-based subscription filtering
3. **Server:** Snapshot generation for each topic type
4. **Client:** Subscribe/unsubscribe for dynamic topics
5. **Client:** `AgentStore`, `FileStore`, `TaskStore` — all reactive, all driven by WebSocket events
6. **Client:** Approval flow (WS notification → inline card → REST POST to approve)

### Phase 3 (Week 5-6): Terminal + Optimistic Updates + Polish

1. **Server:** Terminal output batching and streaming
2. **Server:** File watcher integration (watchfiles)
3. **Client:** `TerminalStore` with virtual scrolling
4. **Client:** Optimistic message sending with reconciliation
5. **Client:** Notification store with priority sorting
6. **Type generation:** Pydantic → TypeScript pipeline in CI

### Phase 4 (Week 7+): Advanced Features

1. **Server:** WebSocket compression (permessage-deflate) if bandwidth is a concern
2. **Server:** Per-connection rate limiting for commands
3. **Client:** IndexedDB caching for offline message viewing
4. **Client:** Service Worker for background sync
5. **Client:** Multi-session support (subscribe to multiple chat sessions simultaneously)

---

## Appendix: Decision Log

| Decision | Chosen | Rejected | Why |
|----------|--------|----------|-----|
| Transport | WebSocket | SSE, Socket.IO | Bidirectional, single connection, full control |
| Wire format | JSON | MessagePack, Protobuf | Debuggable, fast enough, no build step |
| Sync model | Sequence numbers + replay | CRDTs, OT, full event sourcing | Simple, proven (Discord/Linear), matches our single-user model |
| Conflict resolution | Last-write-wins | CRDTs | One user + one agent = no real conflicts |
| Server library | Raw Starlette WS | Socket.IO, fastapi-websocket-pubsub | Full control, no unnecessary abstraction |
| Client state | Svelte 5 runes ($state) | Svelte stores, external state lib | Native, performant, no extra dependency |
| Type sharing | Pydantic → TypeScript codegen | Manual types, Protobuf schema, GraphQL | Single source of truth in Python, auto-generated TS |
| CRUD operations | REST | Everything over WebSocket | Cacheable, proper HTTP semantics, better tooling |
| High-frequency rendering | requestAnimationFrame batching | Direct DOM updates per token | Smooth 60fps, no dropped frames |
| Initial state | Snapshot on subscribe | Full DB sync, lazy loading only | Fast time-to-interactive, then live updates |
