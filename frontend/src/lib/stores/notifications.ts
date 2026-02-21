/**
 * Notification Governance Store
 *
 * Rules (from spec):
 *  - Max 5 push notifications per day
 *  - Quiet hours: 23:00–08:00 CET
 *  - Tracks iOS Home Screen install prompt
 */

import { writable, get } from 'svelte/store';

const STORAGE_KEY = 'autopoiesis:notification-state';
const MAX_DAILY_PUSH = 5;
const QUIET_START = 23; // 23:00 CET
const QUIET_END = 8; // 08:00 CET

interface NotificationState {
	granted: boolean;
	dailyCount: number;
	lastReset: string; // ISO date (YYYY-MM-DD)
	iosPromptShown: boolean;
	iosPromptDismissed: boolean;
}

function loadState(): NotificationState {
	if (typeof localStorage === 'undefined') {
		return defaultState();
	}
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		return raw ? (JSON.parse(raw) as NotificationState) : defaultState();
	} catch {
		return defaultState();
	}
}

function defaultState(): NotificationState {
	return {
		granted: false,
		dailyCount: 0,
		lastReset: todayKey(),
		iosPromptShown: false,
		iosPromptDismissed: false,
	};
}

function todayKey(): string {
	return new Date().toISOString().split('T')[0];
}

/** CET offset: UTC+1 (standard) or UTC+2 (DST) — approximate with +1 */
function cetHour(): number {
	const now = new Date();
	return (now.getUTCHours() + 1) % 24;
}

function isQuietHours(): boolean {
	const h = cetHour();
	// 23:00–24:00 or 00:00–08:00
	return h >= QUIET_START || h < QUIET_END;
}

export const notificationState = writable<NotificationState>(loadState());

notificationState.subscribe((state) => {
	if (typeof localStorage === 'undefined') return;
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
	} catch {}
});

// ---------- actions ----------

export async function requestPermission(): Promise<boolean> {
	if (typeof Notification === 'undefined') return false;
	const result = await Notification.requestPermission();
	const granted = result === 'granted';
	notificationState.update((s) => ({ ...s, granted }));
	return granted;
}

/** Attempt to send a push notification, respecting governance rules */
export function sendPush(title: string, body: string, options?: NotificationOptions): boolean {
	const state = get(notificationState);

	if (!state.granted) return false;
	if (isQuietHours()) return false;

	// Reset daily count if new day
	const today = todayKey();
	if (state.lastReset !== today) {
		notificationState.update((s) => ({ ...s, dailyCount: 0, lastReset: today }));
	}

	if (state.dailyCount >= MAX_DAILY_PUSH) return false;

	try {
		new Notification(title, {
			body,
			icon: '/icons/icon-192.png',
			badge: '/icons/icon-192.png',
			...options,
		});
		notificationState.update((s) => ({ ...s, dailyCount: s.dailyCount + 1 }));
		return true;
	} catch {
		return false;
	}
}

export function dismissIosPrompt(): void {
	notificationState.update((s) => ({ ...s, iosPromptDismissed: true, iosPromptShown: true }));
}

export function markIosPromptShown(): void {
	notificationState.update((s) => ({ ...s, iosPromptShown: true }));
}

/** Check if iOS standalone mode install prompt should be shown */
export function shouldShowIosInstallPrompt(): boolean {
	const state = get(notificationState);
	if (state.iosPromptDismissed) return false;

	// Detect iOS Safari (not already installed)
	const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
	const isInStandaloneMode =
		'standalone' in window.navigator && (window.navigator as { standalone?: boolean }).standalone;
	return isIos && !isInStandaloneMode;
}
