<script lang="ts">
	/**
	 * Active State — full-page view of unresolved resolvable events.
	 * On mobile this is the tab destination; on desktop the drawer handles it.
	 */
	import { activeState, clearResolved } from '$lib/stores/active-state';
	import EventRenderer from '$lib/components/EventRenderer.svelte';
</script>

<svelte:head>
	<title>Active State · Autopoiesis</title>
</svelte:head>

<div class="mx-auto max-w-2xl px-3 py-4">
	<div class="mb-4 flex items-center justify-between">
		<div>
			<h1 class="text-base font-semibold text-zinc-100">Active State</h1>
			<p class="text-xs text-zinc-600 mt-0.5">
				{$activeState.length} unresolved item{$activeState.length === 1 ? '' : 's'}
			</p>
		</div>
		{#if $activeState.length > 0}
			<button
				class="text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
				onclick={clearResolved}
			>
				Clear resolved
			</button>
		{/if}
	</div>

	<div class="space-y-3">
		{#each $activeState as event (event.meta.id)}
			<article>
				<EventRenderer {event} />
			</article>
		{:else}
			<div class="flex flex-col items-center justify-center py-20 text-center">
				<div class="mb-3 text-4xl opacity-20">📋</div>
				<p class="text-sm text-zinc-600">Nothing pending</p>
				<p class="mt-1 text-xs text-zinc-700">Resolved items are removed automatically</p>
			</div>
		{/each}
	</div>
</div>
