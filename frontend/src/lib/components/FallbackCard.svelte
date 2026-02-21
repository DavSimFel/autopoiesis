<script lang="ts">
	/**
	 * FallbackCard — renders unknown UIEvent types as formatted JSON.
	 * Ensures the shell never crashes on new server event types.
	 */
	import type { UIEvent } from '$lib/types';
	import { formatRelativeTime } from '$lib/utils';

	let {
		event,
	}: {
		event: UIEvent;
	} = $props();

	let expanded = $state(false);
</script>

<div class="rounded-xl border border-zinc-800/50 bg-zinc-900/40 p-4">
	<div class="mb-2 flex items-center justify-between">
		<div class="flex items-center gap-2">
			<span class="text-zinc-600">?</span>
			<code class="text-xs text-zinc-500">{event.type}</code>
		</div>
		<button
			class="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
			onclick={() => (expanded = !expanded)}
		>
			{expanded ? '▲ collapse' : '▼ expand'}
		</button>
	</div>

	{#if expanded}
		<div class="overflow-auto rounded-lg bg-zinc-950 p-3">
			<pre class="text-xs text-zinc-400">{JSON.stringify(event, null, 2)}</pre>
		</div>
	{:else}
		<div class="text-xs text-zinc-600 italic">
			Unknown event type — expand to inspect
		</div>
	{/if}

	<div class="mt-2 text-right text-[10px] text-zinc-700">
		{formatRelativeTime(event.meta.timestamp)}
	</div>
</div>
