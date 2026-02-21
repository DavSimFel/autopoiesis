/**
 * MCP Client — Streamable HTTP + SSE
 *
 * Deployment topology:
 *  PWA  →  autopoiesis.feldhofer.cc  (CF Pages, static SvelteKit)
 *            │
 *            └── /mcp/*  →  SvelteKit server proxy route
 *                              │
 *                              └── autopoiesis-api.feldhofer.cc/mcp/*
 *                                    (CF Tunnel → localhost:8420)
 *
 * The browser always calls same-origin /mcp (via the SvelteKit proxy), which
 * eliminates CORS entirely. The proxy forwards CF Access cookies server-side.
 *
 * Auth: credentials: 'include' ensures the browser sends its CF Access session
 * cookie on every request. Do NOT use service tokens — the proxy handles that.
 *
 * The server returns JSON only. The shell owns all rendering.
 */

import { pushEvent } from '$lib/stores/active-state';
import type { UIEvent, UINotification } from '$lib/types';

// ---------- Config ----------

// Defaults to same-origin /mcp (proxied). Override VITE_MCP_BASE_URL in .env
// to point directly at autopoiesis-api.feldhofer.cc/mcp for local dev without proxy.
const MCP_BASE = import.meta.env.VITE_MCP_BASE_URL ?? '/mcp';
const SSE_ENDPOINT = import.meta.env.VITE_SSE_ENDPOINT ?? `${MCP_BASE}/sse`;

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
const RECONNECT_JITTER_MS = 500;

// ---------- Types ----------

export interface MCPToolCallResult {
	content: Array<{ type: 'text'; text: string }>;
	isError?: boolean;
}

export interface MCPError {
	code: number;
	message: string;
	data?: unknown;
}

export class MCPClientError extends Error {
	constructor(
		public readonly code: number,
		message: string,
		public readonly data?: unknown,
	) {
		super(message);
		this.name = 'MCPClientError';
	}
}

// ---------- Tool calls ----------

let _requestId = 0;

/**
 * Call an MCP tool via Streamable HTTP POST.
 * Uses credentials: 'include' so CF Access session cookies are forwarded.
 */
export async function callTool(
	tool: string,
	args: Record<string, unknown> = {},
): Promise<MCPToolCallResult> {
	const id = String(++_requestId);

	const resp = await fetch(MCP_BASE, {
		method: 'POST',
		credentials: 'include',
		headers: {
			'Content-Type': 'application/json',
			Accept: 'application/json, text/event-stream',
		},
		body: JSON.stringify({
			jsonrpc: '2.0',
			method: 'tools/call',
			params: {
				name: tool,
				arguments: args,
			},
			id,
		}),
	});

	if (!resp.ok) {
		throw new MCPClientError(resp.status, `HTTP ${resp.status}: ${resp.statusText}`);
	}

	const contentType = resp.headers.get('content-type') ?? '';

	// Streamable HTTP: server may return SSE stream or plain JSON
	if (contentType.includes('text/event-stream')) {
		return parseStreamedResponse(resp);
	}

	const json = await resp.json();

	if (json.error) {
		const err = json.error as MCPError;
		throw new MCPClientError(err.code, err.message, err.data);
	}

	return json.result as MCPToolCallResult;
}

/** Parse a streamed (SSE) tool call response, collecting all data chunks */
async function parseStreamedResponse(resp: Response): Promise<MCPToolCallResult> {
	const reader = resp.body?.getReader();
	if (!reader) throw new MCPClientError(-1, 'No response body');

	const decoder = new TextDecoder();
	let buffer = '';
	let result: MCPToolCallResult | null = null;

	while (true) {
		const { done, value } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });

		const lines = buffer.split('\n');
		buffer = lines.pop() ?? '';

		for (const line of lines) {
			if (line.startsWith('data: ')) {
				const data = line.slice(6).trim();
				if (data === '[DONE]') continue;
				try {
					const parsed = JSON.parse(data);
					if (parsed.result) result = parsed.result;
					if (parsed.error) {
						const err = parsed.error as MCPError;
						throw new MCPClientError(err.code, err.message, err.data);
					}
				} catch (e) {
					if (e instanceof MCPClientError) throw e;
					// Skip malformed lines
				}
			}
		}
	}

	if (!result) throw new MCPClientError(-1, 'Empty streamed response');
	return result;
}

// ---------- SSE subscription ----------

export type SSEStatus = 'connecting' | 'connected' | 'reconnecting' | 'closed';

type StatusCallback = (status: SSEStatus) => void;
type EventCallback = (event: UIEvent) => void;

interface SSESubscription {
	close: () => void;
}

/**
 * Connect to the MCP SSE endpoint and push incoming UIEvents into the store.
 * Handles exponential backoff reconnection automatically.
 */
export function subscribeSSE(
	onStatus?: StatusCallback,
	onEvent?: EventCallback,
): SSESubscription {
	let eventSource: EventSource | null = null;
	let reconnectAttempt = 0;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let closed = false;

	function connect(): void {
		onStatus?.('connecting');

		// SSE must be GET; credentials are included via cookie (CF Access)
		// EventSource doesn't support custom headers, so CF Access cookie must
		// already be set in the browser (handled by the CF Access flow on load).
		eventSource = new EventSource(SSE_ENDPOINT, { withCredentials: true });

		eventSource.addEventListener('open', () => {
			reconnectAttempt = 0;
			onStatus?.('connected');
		});

		eventSource.addEventListener('message', (ev) => {
			try {
				const notification = JSON.parse(ev.data) as UINotification;
				if (notification.event === 'ui_event' && notification.data) {
					const uiEvent = notification.data;
					pushEvent(uiEvent); // → active-state store
					onEvent?.(uiEvent);
				}
			} catch {
				// Malformed SSE payload — skip
			}
		});

		// Named event types from spec
		eventSource.addEventListener('ui_event', (ev) => {
			try {
				const uiEvent = JSON.parse(ev.data) as UIEvent;
				pushEvent(uiEvent);
				onEvent?.(uiEvent);
			} catch {}
		});

		eventSource.addEventListener('ping', () => {
			// Keep-alive ping — no action needed
		});

		eventSource.onerror = () => {
			eventSource?.close();
			eventSource = null;

			if (closed) return;

			onStatus?.('reconnecting');
			const delay = Math.min(
				RECONNECT_BASE_MS * 2 ** reconnectAttempt + Math.random() * RECONNECT_JITTER_MS,
				RECONNECT_MAX_MS,
			);
			reconnectAttempt++;
			reconnectTimer = setTimeout(connect, delay);
		};
	}

	connect();

	return {
		close(): void {
			closed = true;
			if (reconnectTimer) clearTimeout(reconnectTimer);
			eventSource?.close();
			onStatus?.('closed');
		},
	};
}

// ---------- Skills listing ----------

export interface MCPTool {
	name: string;
	description?: string;
	inputSchema?: {
		type: string;
		properties?: Record<string, { type: string; description?: string }>;
		required?: string[];
	};
}

/** Fetch all available MCP tools (for the More / skills page) */
export async function listTools(): Promise<MCPTool[]> {
	const id = String(++_requestId);
	const resp = await fetch(MCP_BASE, {
		method: 'POST',
		credentials: 'include',
		headers: {
			'Content-Type': 'application/json',
			Accept: 'application/json',
		},
		body: JSON.stringify({
			jsonrpc: '2.0',
			method: 'tools/list',
			params: {},
			id,
		}),
	});

	if (!resp.ok) throw new MCPClientError(resp.status, `HTTP ${resp.status}`);
	const json = await resp.json();
	if (json.error) {
		const err = json.error as MCPError;
		throw new MCPClientError(err.code, err.message);
	}
	return (json.result?.tools as MCPTool[]) ?? [];
}
