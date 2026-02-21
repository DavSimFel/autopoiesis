/**
 * MCP Proxy Route — /mcp/[...path]
 *
 * Proxies all /mcp/* requests to the MCP API server
 * (autopoiesis-api.feldhofer.cc → CF Tunnel → localhost:8420).
 *
 * Benefits:
 *  1. Same-origin — no CORS headers needed on the API server
 *  2. CF Access cookies are forwarded transparently
 *  3. SSE streaming is preserved (no buffering)
 *  4. Works with EventSource (GET /mcp/sse) and fetch POST /mcp
 *
 * The PWA always calls /mcp/* (same origin). This route forwards the request
 * and streams the response back verbatim, including SSE streams.
 */

import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

/** Upstream API base — configurable via MCP_API_URL in .env */
const API_BASE = (env.MCP_API_URL ?? 'https://autopoiesis-api.feldhofer.cc').replace(/\/$/, '');

/**
 * Build the upstream URL for a given path slug and original request URL.
 * Preserves query string parameters.
 */
function upstreamUrl(path: string, requestUrl: URL): string {
	const upstream = new URL(`${API_BASE}/mcp/${path}`);
	// Forward query params (e.g., for SSE: ?clientId=xxx)
	requestUrl.searchParams.forEach((value, key) => {
		upstream.searchParams.set(key, value);
	});
	return upstream.toString();
}

/**
 * Forward headers from the browser request to the upstream.
 * Critically: forwards the Cookie header so CF Access session is passed through.
 * Strips hop-by-hop headers that must not be forwarded.
 */
function forwardHeaders(incoming: Headers, requestUrl: URL): Headers {
	const HOP_BY_HOP = new Set([
		'connection',
		'keep-alive',
		'proxy-authenticate',
		'proxy-authorization',
		'te',
		'trailers',
		'transfer-encoding',
		'upgrade',
		// host must be set to the upstream host, not forwarded from browser
		'host',
	]);

	const out = new Headers();

	incoming.forEach((value, key) => {
		if (!HOP_BY_HOP.has(key.toLowerCase())) {
			out.set(key, value);
		}
	});

	// Tell the upstream where the original request came from
	out.set('X-Forwarded-Host', requestUrl.hostname);
	out.set('X-Forwarded-Proto', requestUrl.protocol.replace(':', ''));

	return out;
}

/** Generic proxy handler — works for GET, POST, PUT, DELETE, OPTIONS */
async function proxy(event: Parameters<RequestHandler>[0]): Promise<Response> {
	const { params, request, url } = event;
	const path = params.path ?? '';

	const upstream = upstreamUrl(path, url);
	const headers = forwardHeaders(request.headers, url);

	// Read body for non-GET/HEAD requests
	const hasBody = !['GET', 'HEAD'].includes(request.method);
	const body = hasBody ? await request.arrayBuffer() : undefined;

	let upstreamResponse: Response;
	try {
		upstreamResponse = await fetch(upstream, {
			method: request.method,
			headers,
			body: hasBody ? body : undefined,
			// Prevent Node from following redirects so we can forward them to the browser
			redirect: 'manual',
			// @ts-expect-error — Node 18+ fetch supports duplex for streaming bodies
			duplex: hasBody ? 'half' : undefined,
		});
	} catch (err) {
		const message = err instanceof Error ? err.message : 'Upstream unreachable';
		return new Response(
			JSON.stringify({
				jsonrpc: '2.0',
				error: { code: -32603, message: `Proxy error: ${message}` },
				id: null,
			}),
			{
				status: 502,
				headers: { 'Content-Type': 'application/json' },
			},
		);
	}

	// Forward response headers, stripping hop-by-hop
	const responseHeaders = new Headers();
	upstreamResponse.headers.forEach((value, key) => {
		const lower = key.toLowerCase();
		// Forward SSE-critical headers
		if (
			lower === 'content-type' ||
			lower === 'cache-control' ||
			lower === 'x-accel-buffering' ||
			lower === 'access-control-allow-origin' ||
			lower === 'access-control-allow-credentials' ||
			lower === 'set-cookie'
		) {
			responseHeaders.set(key, value);
		}
	});

	// For SSE responses, ensure no buffering so events reach the browser immediately
	const contentType = upstreamResponse.headers.get('content-type') ?? '';
	if (contentType.includes('text/event-stream')) {
		responseHeaders.set('X-Accel-Buffering', 'no');
		responseHeaders.set('Cache-Control', 'no-cache, no-transform');
	}

	// Stream the response body straight through (critical for SSE and large JSON)
	return new Response(upstreamResponse.body, {
		status: upstreamResponse.status,
		statusText: upstreamResponse.statusText,
		headers: responseHeaders,
	});
}

// Export all HTTP methods SvelteKit will route through this handler
export const GET: RequestHandler = proxy;
export const POST: RequestHandler = proxy;
export const PUT: RequestHandler = proxy;
export const DELETE: RequestHandler = proxy;
export const PATCH: RequestHandler = proxy;
export const OPTIONS: RequestHandler = proxy;
