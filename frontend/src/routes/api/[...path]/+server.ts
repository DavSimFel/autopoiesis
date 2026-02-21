/**
 * REST API Proxy Route — /api/[...path]
 *
 * Proxies all /api/* requests to the upstream API server
 * (autopoiesis-api.feldhofer.cc → CF Tunnel → localhost:8420).
 *
 * Benefits:
 *  1. Same-origin — no CORS headers needed on the API server
 *  2. CF Access cookies are forwarded transparently
 *  3. SSE streaming is preserved (no buffering) for /api/stream
 *  4. Works with EventSource (GET /api/stream) and fetch POST /api/tools/*
 */

import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

/** Upstream API base — configurable via MCP_API_URL in .env */
const API_BASE = (env.MCP_API_URL ?? 'https://autopoiesis-api.feldhofer.cc').replace(/\/$/, '');

function upstreamUrl(path: string, requestUrl: URL): string {
	const upstream = new URL(`${API_BASE}/api/${path}`);
	requestUrl.searchParams.forEach((value, key) => {
		upstream.searchParams.set(key, value);
	});
	return upstream.toString();
}

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
		'host',
	]);

	const out = new Headers();
	incoming.forEach((value, key) => {
		if (!HOP_BY_HOP.has(key.toLowerCase())) {
			out.set(key, value);
		}
	});
	out.set('X-Forwarded-Host', requestUrl.hostname);
	out.set('X-Forwarded-Proto', requestUrl.protocol.replace(':', ''));
	return out;
}

async function proxy(event: Parameters<RequestHandler>[0]): Promise<Response> {
	const { params, request, url } = event;
	const path = params.path ?? '';

	const upstream = upstreamUrl(path, url);
	const headers = forwardHeaders(request.headers, url);

	const hasBody = !['GET', 'HEAD'].includes(request.method);
	const body = hasBody ? await request.arrayBuffer() : undefined;

	let upstreamResponse: Response;
	try {
		upstreamResponse = await fetch(upstream, {
			method: request.method,
			headers,
			body: hasBody ? body : undefined,
			redirect: 'manual',
			// @ts-expect-error — Node 18+ fetch supports duplex for streaming bodies
			duplex: hasBody ? 'half' : undefined,
		});
	} catch (err) {
		const message = err instanceof Error ? err.message : 'Upstream unreachable';
		return new Response(
			JSON.stringify({ error: `Proxy error: ${message}` }),
			{
				status: 502,
				headers: { 'Content-Type': 'application/json' },
			},
		);
	}

	const responseHeaders = new Headers();
	upstreamResponse.headers.forEach((value, key) => {
		const lower = key.toLowerCase();
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

	// For SSE responses (/api/stream), ensure no buffering
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
