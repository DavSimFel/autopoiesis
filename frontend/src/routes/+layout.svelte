<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';

	import { subscribeStream } from '$lib/api-client';
	import type { SSEStatus } from '$lib/api-client';
	import { pushEvent } from '$lib/stores/active-state';
	import { activeCount, activeState } from '$lib/stores/active-state';
	import { activeTab, activeDrawerOpen, focusedEvent, isFocusModeActive, closeFocus } from '$lib/stores/nav';
	import { shouldShowIosInstallPrompt } from '$lib/stores/notifications';

	import ConnectionStatus from '$lib/components/ConnectionStatus.svelte';
	import ActiveStateDrawer from '$lib/components/ActiveStateDrawer.svelte';
	import EventRenderer from '$lib/components/EventRenderer.svelte';
	import IosInstallBanner from '$lib/components/IosInstallBanner.svelte';

	let { children } = $props();

	let sseStatus = $state<SSEStatus>('connecting');
	let showIosBanner = $state(false);

	// Nav items (mobile bottom bar + desktop sidebar)
	const navItems = [
		{ id: 'chat', label: 'Chat', icon: '💬', path: '/chat' },
		{ id: 'active', label: 'Active', icon: '📋', path: '/active' },
		{ id: 'stream', label: 'Feed', icon: '🏠', path: '/' },
		{ id: 'alerts', label: 'Alerts', icon: '🔔', path: '/alerts' },
		{ id: 'more', label: 'More', icon: '⋯', path: '/more' },
	] as const;

	onMount(() => {
		// SSE subscription — EventSource handles reconnection natively
		sseStatus = 'connecting';
		const es = subscribeStream((event) => {
			pushEvent(event);
		});

		es.addEventListener('open', () => {
			sseStatus = 'connected';
		});

		es.addEventListener('error', () => {
			// EventSource will reconnect automatically; reflect that in status
			sseStatus = es.readyState === EventSource.CLOSED ? 'closed' : 'reconnecting';
		});

		// iOS install prompt
		if (shouldShowIosInstallPrompt()) {
			showIosBanner = true;
		}

		return () => {
			es.close();
			sseStatus = 'closed';
		};
	});

	function handleNavClick(path: string, id: string) {
		if (id === 'active') {
			// Toggle drawer on mobile, navigate on desktop
			activeDrawerOpen.update((v) => !v);
			return;
		}
		goto(path);
	}

	function getBadge(id: string): number | null {
		if (id === 'active') return $activeCount > 0 ? $activeCount : null;
		return null;
	}
</script>

<div class="flex h-svh flex-col bg-zinc-950 text-zinc-50 md:flex-row">
	<!-- ============================================================
	     Desktop: Left sidebar navigation
	     ============================================================ -->
	<nav class="hidden md:flex md:w-16 md:flex-col md:items-center md:border-r md:border-zinc-800 md:bg-zinc-950 md:py-4">
		<!-- Logo -->
		<div class="mb-6 flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-800 text-lg">
			⚡
		</div>

		<!-- Nav links -->
		<div class="flex flex-1 flex-col items-center gap-1">
			{#each navItems as item}
				{@const badge = getBadge(item.id)}
				<button
					class="relative flex h-10 w-10 items-center justify-center rounded-xl text-xl transition-colors
						{$page.url.pathname === item.path || (item.id === 'active' && $activeDrawerOpen)
							? 'bg-zinc-800 text-zinc-100'
							: 'text-zinc-600 hover:bg-zinc-900 hover:text-zinc-300'}"
					onclick={() => handleNavClick(item.path, item.id)}
					title={item.label}
					aria-label={item.label}
				>
					{item.icon}
					{#if badge}
						<span class="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-amber-500 text-[9px] font-bold text-black">
							{badge > 9 ? '9+' : badge}
						</span>
					{/if}
				</button>
			{/each}
		</div>

		<!-- Connection status -->
		<div class="mt-auto flex flex-col items-center gap-1">
			<ConnectionStatus status={sseStatus} />
		</div>
	</nav>

	<!-- ============================================================
	     Main content area
	     ============================================================ -->
	<div class="flex flex-1 min-w-0 flex-col md:flex-row overflow-hidden">
		<!-- Page content -->
		<main class="flex-1 min-w-0 overflow-y-auto">
			<!-- Mobile top bar -->
			<div class="sticky top-0 z-30 flex items-center justify-between border-b border-zinc-900 bg-zinc-950/90 px-4 py-3 pt-safe backdrop-blur-sm md:hidden">
				<div class="text-sm font-semibold text-zinc-300">Autopoiesis</div>
				<ConnectionStatus status={sseStatus} />
			</div>

			{@render children()}
		</main>

		<!-- Desktop: Active State panel (right side) -->
		<ActiveStateDrawer desktop />
	</div>

	<!-- Mobile: Active State drawer (slide-over) -->
	<ActiveStateDrawer />

	<!-- ============================================================
	     Focus mode overlay
	     ============================================================ -->
	{#if $isFocusModeActive && $focusedEvent}
		<div class="fixed inset-0 z-50 flex flex-col bg-zinc-950">
			<!-- Focus toolbar -->
			<div class="flex items-center gap-3 border-b border-zinc-800 px-4 py-3 pt-safe">
				<button
					class="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors"
					onclick={closeFocus}
					aria-label="Back"
				>
					← Back
				</button>
				<span class="text-sm font-medium text-zinc-400">{$focusedEvent.type}</span>
			</div>

			<div class="flex-1 overflow-y-auto p-4 pb-safe">
				<EventRenderer event={$focusedEvent} focusable={false} />
			</div>
		</div>
	{/if}

	<!-- ============================================================
	     Mobile bottom tab bar
	     ============================================================ -->
	<nav class="shrink-0 border-t border-zinc-800 bg-zinc-950/90 backdrop-blur-sm pb-safe md:hidden">
		<div class="flex items-center justify-around">
			{#each navItems as item}
				{@const badge = getBadge(item.id)}
				<button
					class="relative flex flex-col items-center gap-0.5 px-3 py-2 transition-colors
						{$page.url.pathname === item.path || (item.id === 'active' && $activeDrawerOpen)
							? 'text-zinc-100'
							: 'text-zinc-600 active:text-zinc-400'}"
					onclick={() => handleNavClick(item.path, item.id)}
					aria-label={item.label}
				>
					<span class="text-xl leading-none">{item.icon}</span>
					<span class="text-[9px] font-medium">{item.label}</span>
					{#if badge}
						<span class="absolute right-2 top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-amber-500 text-[9px] font-bold text-black">
							{badge > 9 ? '9+' : badge}
						</span>
					{/if}
				</button>
			{/each}
		</div>
	</nav>

	<!-- iOS install banner -->
	{#if showIosBanner}
		<IosInstallBanner ondismiss={() => (showIosBanner = false)} />
	{/if}
</div>
