/**
 * REST API Client
 *
 * Deployment topology:
 *  PWA  →  autopoiesis.feldhofer.cc  (CF Pages, static SvelteKit)
 *            │
 *            └── /api/*  →  SvelteKit server proxy route
 *                              │
 *                              └── autopoiesis-api.feldhofer.cc/api/*
 *                                    (CF Tunnel → localhost:8420)
 *
 * The browser always calls same-origin /api (via the SvelteKit proxy), which
 * eliminates CORS entirely. The proxy forwards CF Access cookies server-side.
 *
 * Auth: credentials: 'include' ensures the browser sends its CF Access session
 * cookie on every request.
 */

import type { UIEvent } from '$lib/types';

const API = '/api';

// ---------- Types ----------

export type SSEStatus = 'connecting' | 'connected' | 'reconnecting' | 'closed';

/** Tool definition returned by the REST API */
export interface Tool {
	name: string;
	description?: string;
	inputSchema?: {
		type: string;
		properties?: Record<string, { type: string; description?: string }>;
		required?: string[];
	};
}

/** Kept for backward compat — MCPTool alias */
export type MCPTool = Tool;

// ---------- REST endpoints ----------

export const getStatus = () =>
	fetch(`${API}/status`, { credentials: 'include' }).then((r) => r.json());

export const getApprovals = () =>
	fetch(`${API}/approvals`, { credentials: 'include' }).then((r) => r.json());

export const submitAction = (action: string, payload: Record<string, unknown>) =>
	fetch(`${API}/actions`, {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ action, ...payload }),
	}).then((r) => r.json());

export const listTools = () =>
	fetch(`${API}/tools`, { credentials: 'include' }).then((r) => r.json());

export const callTool = (name: string, args: Record<string, unknown>) =>
	fetch(`${API}/tools/${name}`, {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(args),
	}).then((r) => r.json());

// ---------- SSE stream ----------

export function subscribeStream(onEvent: (e: UIEvent) => void): EventSource {
	const es = new EventSource(`${API}/stream`, { withCredentials: true });
	es.onmessage = (ev) => onEvent(JSON.parse(ev.data) as UIEvent);
	return es;
}
