/**
 * Navigation Store
 *
 * Manages the three surfaces:
 *  - stream: default activity feed
 *  - active: Active State drawer / panel (persistent inbox)
 *  - focus: full-screen single-item view
 *  - chat: chat interface
 *  - more: skill listing (escape hatch)
 */

import { writable, derived } from 'svelte/store';
import type { NavTab, UIEvent } from '$lib/types';

export const activeTab = writable<NavTab>('stream');

/** For Focus mode — the event currently in focus */
export const focusedEvent = writable<UIEvent | null>(null);

/** Whether the Active State drawer is open (mobile slide-out) */
export const activeDrawerOpen = writable(false);

export function navigateTo(tab: NavTab): void {
	activeTab.set(tab);
	if (tab !== 'active') {
		activeDrawerOpen.set(false);
	}
}

export function openFocus(event: UIEvent): void {
	focusedEvent.set(event);
	activeTab.set('stream'); // focus overlays stream
}

export function closeFocus(): void {
	focusedEvent.set(null);
}

export function toggleActiveDrawer(): void {
	activeDrawerOpen.update((v) => !v);
}

export const isFocusModeActive = derived(focusedEvent, ($e) => $e !== null);
