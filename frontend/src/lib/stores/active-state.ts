/**
 * Active State Store
 *
 * Items with meta.resolvable: true persist in this store until explicitly
 * resolved. This is the "persistent inbox" — the escape hatch from stream noise.
 *
 * Architecture:
 *  allEvents  → writable, source of truth (backed by localStorage)
 *  activeState → derived, only unresolved resolvable items sorted by priority
 *  streamEvents → derived, all events for the stream feed
 */

import { writable, derived, get } from 'svelte/store';
import type { UIEvent } from '$lib/types';

const STORAGE_KEY = 'autopoiesis:active-state';
const MAX_STREAM_EVENTS = 200; // cap to avoid memory bloat

// ---------- helpers ----------

function loadFromStorage(): UIEvent[] {
	if (typeof localStorage === 'undefined') return [];
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		return raw ? (JSON.parse(raw) as UIEvent[]) : [];
	} catch {
		return [];
	}
}

function saveToStorage(events: UIEvent[]): void {
	if (typeof localStorage === 'undefined') return;
	try {
		// Only persist resolvable items — ephemeral stream events don't need storage
		const resolvable = events.filter((e) => e.meta.resolvable);
		localStorage.setItem(STORAGE_KEY, JSON.stringify(resolvable));
	} catch {
		// Storage quota exceeded or private mode — fail silently
	}
}

// ---------- stores ----------

/** Source-of-truth store: all events received this session + persisted resolvables */
const _allEvents = writable<UIEvent[]>(loadFromStorage());

/** Subscribe to persist resolvable items on every change */
_allEvents.subscribe(saveToStorage);

export const allEvents = {
	..._allEvents,
	subscribe: _allEvents.subscribe,
};

/**
 * Active State — unresolved resolvable items sorted by priority (ascending = most urgent first).
 * This is the "inbox that never loses things".
 */
export const activeState = derived(_allEvents, ($events) =>
	$events
		.filter((e) => e.meta.resolvable && !e.meta.resolved)
		.sort((a, b) => a.meta.priority - b.meta.priority),
);

/** Stream feed — all non-resolved events, capped, newest first */
export const streamEvents = derived(_allEvents, ($events) =>
	[...$events]
		.filter((e) => !e.meta.resolved || e.meta.resolvable)
		.sort((a, b) => new Date(b.meta.timestamp).getTime() - new Date(a.meta.timestamp).getTime())
		.slice(0, MAX_STREAM_EVENTS),
);

/** Count of unresolved active items — used for badge on Active tab */
export const activeCount = derived(
	activeState,
	($active) => $active.length,
);

// ---------- actions ----------

/** Append a new event from SSE / MCP response */
export function pushEvent(event: UIEvent): void {
	_allEvents.update((events) => {
		// Deduplicate by meta.id
		const exists = events.some((e) => e.meta.id === event.meta.id);
		if (exists) return events;

		const next = [...events, event];
		// Trim non-resolvable events to cap
		const resolvable = next.filter((e) => e.meta.resolvable);
		const ephemeral = next
			.filter((e) => !e.meta.resolvable)
			.slice(-MAX_STREAM_EVENTS);
		return [...resolvable, ...ephemeral];
	});
}

/** Mark an event as resolved (removes from Active State) */
export function resolveEvent(id: string): void {
	_allEvents.update((events) =>
		events.map((e) =>
			e.meta.id === id
				? { ...e, meta: { ...e.meta, resolved: true, resolvedAt: new Date().toISOString() } }
				: e,
		),
	);
}

/** Dismiss an event entirely (remove from all views) */
export function dismissEvent(id: string): void {
	_allEvents.update((events) => events.filter((e) => e.meta.id !== id));
}

/** Clear all resolved items (housekeeping) */
export function clearResolved(): void {
	_allEvents.update((events) => events.filter((e) => !e.meta.resolved));
}

/** Get a single event by id */
export function getEvent(id: string): UIEvent | undefined {
	return get(_allEvents).find((e) => e.meta.id === id);
}
