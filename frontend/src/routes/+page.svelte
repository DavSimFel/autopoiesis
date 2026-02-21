<script lang="ts">
	/**
	 * Stream — default feed surface
	 * Shows all events newest-first, rendered via EventRenderer → registry.
	 */
	import { streamEvents } from '$lib/stores/active-state';
	import EventRenderer from '$lib/components/EventRenderer.svelte';
</script>

<svelte:head>
	<title>Feed · Autopoiesis</title>
</svelte:head>

<div class="mx-auto max-w-2xl px-3 py-4 space-y-3">
	{#if $streamEvents.length === 0}
		<!-- Empty state -->
		<div class="flex flex-col items-center justify-center py-20 text-center">
			<div class="mb-3 text-4xl opacity-20">⚡</div>
			<p class="text-sm text-zinc-600">Waiting for events…</p>
			<p class="mt-1 text-xs text-zinc-700">The agent will push updates here in real time</p>
		</div>
	{:else}
		{#each $streamEvents as event (event.meta.id)}
			<article class="relative">
				<!-- Priority indicator strip -->
				{#if event.meta.priority <= 2}
					<div class="absolute -left-1 top-0 bottom-0 w-0.5 rounded-full bg-amber-500/60"></div>
				{/if}
				<EventRenderer {event} />
			</article>
		{/each}
	{/if}
</div>
