<script lang="ts">
	/**
	 * Active State Drawer — slide-out panel of unresolved resolvable events.
	 * Mobile: bottom sheet / side drawer
	 * Desktop: right panel (always visible)
	 */
	import { activeState, clearResolved } from '$lib/stores/active-state';
	import { activeDrawerOpen } from '$lib/stores/nav';
	import EventRenderer from './EventRenderer.svelte';

	let {
		desktop = false,
	}: {
		desktop?: boolean;
	} = $props();
</script>

{#if desktop}
	<!-- Desktop: always-visible right panel -->
	<aside class="flex h-full w-80 shrink-0 flex-col border-l border-zinc-800 bg-zinc-950">
		<div class="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
			<h2 class="text-sm font-semibold text-zinc-300">Active State</h2>
			{#if $activeState.length > 0}
				<button
					class="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
					onclick={clearResolved}
				>
					Clear resolved
				</button>
			{/if}
		</div>

		<div class="flex-1 overflow-y-auto p-3 space-y-3">
			{#each $activeState as event (event.meta.id)}
				<EventRenderer {event} focusable={false} />
			{:else}
				<div class="flex h-full items-center justify-center text-sm text-zinc-600">
					Nothing pending ✓
				</div>
			{/each}
		</div>
	</aside>

{:else}
	<!-- Mobile: slide-over drawer -->
	{#if $activeDrawerOpen}
		<!-- Backdrop -->
		<button
			class="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
			onclick={() => activeDrawerOpen.set(false)}
			aria-label="Close drawer"
		></button>

		<!-- Panel -->
		<div
			class="fixed inset-y-0 right-0 z-50 flex w-[min(360px,90vw)] flex-col
				border-l border-zinc-800 bg-zinc-950 shadow-2xl"
		>
			<div class="flex items-center justify-between border-b border-zinc-800 px-4 py-3 pt-safe">
				<h2 class="text-sm font-semibold text-zinc-300">Active State</h2>
				<button
					class="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors"
					onclick={() => activeDrawerOpen.set(false)}
					aria-label="Close"
				>
					✕
				</button>
			</div>

			<div class="flex-1 overflow-y-auto p-3 space-y-3 pb-safe">
				{#each $activeState as event (event.meta.id)}
					<EventRenderer {event} focusable={false} />
				{:else}
					<div class="flex h-full items-center justify-center text-sm text-zinc-600 py-12">
						Nothing pending ✓
					</div>
				{/each}
			</div>
		</div>
	{/if}
{/if}
