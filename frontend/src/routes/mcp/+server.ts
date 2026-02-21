/**
 * MCP Proxy — root /mcp endpoint
 *
 * Handles POST /mcp (JSON-RPC tool calls) and GET /mcp (health / initialize).
 * The [...path] catch-all handles /mcp/sse, /mcp/tools/*, etc.
 *
 * Re-exports the same proxy logic for consistency.
 */

import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const API_BASE = (env.MCP_API_URL ?? 'https://autopoiesis-api.feldhofer.cc').replace(/\/$/, '');
const UPSTREAM = `${API_BASE}/mcp`;

const HOP_BY_HOP = new Set([
	'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
	'te', 'trailers', 'transfer-encoding', 'upgrade', 'host',
]);

function forwardHeaders(incoming: Headers, requestUrl: URL): Headers {
	const out = new Headers();
	incoming.forEach((value, key) => {
		if (!HOP_BY_HOP.has(key.toLowerCase())) out.set(key, value);
	});
	out.set('X-Forwarded-Host', requestUrl.hostname);
	out.set('X-Forwarded-Proto', requestUrl.protocol.replace(':', ''));
	return out;
}

async function proxy(event: Parameters<RequestHandler>[0]): Promise<Response> {
	const { request, url } = event;

	// Forward query params
	const upstream = new URL(UPSTREAM);
	url.searchParams.forEach((value, key) => upstream.searchParams.set(key, value));

	const headers = forwardHeaders(request.headers, url);
	const hasBody = !['GET', 'HEAD'].includes(request.method);
	const body = hasBody ? await request.arrayBuffer() : undefined;

	let upstreamResponse: Response;
	try {
		upstreamResponse = await fetch(upstream.toString(), {
			method: request.method,
			headers,
			body: hasBody ? body : undefined,
			redirect: 'manual',
		});
	} catch (err) {
		const message = err instanceof Error ? err.message : 'Upstream unreachable';
		return new Response(
			JSON.stringify({
				jsonrpc: '2.0',
				error: { code: -32603, message: `Proxy error: ${message}` },
				id: null,
			}),
			{ status: 502, headers: { 'Content-Type': 'application/json' } },
		);
	}

	const responseHeaders = new Headers();
	upstreamResponse.headers.forEach((value, key) => {
		const lower = key.toLowerCase();
		if (['content-type', 'cache-control', 'x-accel-buffering',
			 'access-control-allow-origin', 'access-control-allow-credentials',
			 'set-cookie'].includes(lower)) {
			responseHeaders.set(key, value);
		}
	});

	const contentType = upstreamResponse.headers.get('content-type') ?? '';
	if (contentType.includes('text/event-stream')) {
		responseHeaders.set('X-Accel-Buffering', 'no');
		responseHeaders.set('Cache-Control', 'no-cache, no-transform');
	}

	return new Response(upstreamResponse.body, {
		status: upstreamResponse.status,
		statusText: upstreamResponse.statusText,
		headers: responseHeaders,
	});
}

export const GET: RequestHandler = proxy;
export const POST: RequestHandler = proxy;
export const PUT: RequestHandler = proxy;
export const DELETE: RequestHandler = proxy;
export const PATCH: RequestHandler = proxy;
export const OPTIONS: RequestHandler = proxy;
