<script lang="ts">
	import type { UIEvent, ToolCallData } from '$lib/types';
	import { formatRelativeTime, formatDuration } from '$lib/utils';

	let {
		event,
	}: {
		event: UIEvent<ToolCallData>;
	} = $props();

	const d = $derived(event.data);
	let expanded = $state(false);

	const statusConfig: Record<string, { color: string; icon: string; label: string }> = {
		pending: { color: 'text-zinc-500', icon: '○', label: 'Pending' },
		running: { color: 'text-amber-400', icon: '◌', label: 'Running' },
		success: { color: 'text-emerald-400', icon: '✓', label: 'Done' },
		error: { color: 'text-red-400', icon: '✕', label: 'Error' },
	};

	const cfg = $derived(statusConfig[d.status] ?? statusConfig.pending);
</script>

<div class="rounded-lg border border-zinc-800/60 bg-zinc-900/40 overflow-hidden">
	<!-- Header row — always visible -->
	<button
		class="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-zinc-800/30 transition-colors"
		onclick={() => (expanded = !expanded)}
	>
		<!-- Status icon -->
		<span class="shrink-0 text-sm {cfg.color} {d.status === 'running' ? 'animate-spin' : ''}">
			{cfg.icon}
		</span>

		<!-- Tool name -->
		<span class="flex-1 min-w-0 truncate font-mono text-xs text-zinc-300">{d.toolName}()</span>

		<!-- Duration -->
		{#if d.duration !== undefined}
			<span class="shrink-0 text-[10px] text-zinc-600">{formatDuration(d.duration)}</span>
		{/if}

		<!-- Expand chevron -->
		<span class="shrink-0 text-[10px] text-zinc-600">{expanded ? '▲' : '▼'}</span>
	</button>

	<!-- Expanded: args + result -->
	{#if expanded}
		<div class="border-t border-zinc-800/60 bg-zinc-950/50">
			<!-- Args -->
			<div class="p-3">
				<div class="mb-1 text-[10px] uppercase tracking-wider text-zinc-600">Arguments</div>
				<pre class="overflow-auto text-xs text-zinc-400">{JSON.stringify(d.args, null, 2)}</pre>
			</div>

			<!-- Result / Error -->
			{#if d.status === 'success' && d.result !== undefined}
				<div class="border-t border-zinc-800/60 p-3">
					<div class="mb-1 text-[10px] uppercase tracking-wider text-emerald-600">Result</div>
					<pre class="overflow-auto text-xs text-emerald-400/80">
						{typeof d.result === 'string' ? d.result : JSON.stringify(d.result, null, 2)}
					</pre>
				</div>
			{:else if d.status === 'error' && d.error}
				<div class="border-t border-red-900/30 p-3">
					<div class="mb-1 text-[10px] uppercase tracking-wider text-red-600">Error</div>
					<pre class="overflow-auto text-xs text-red-400">{d.error}</pre>
				</div>
			{/if}

			<div class="px-3 pb-2 text-right text-[10px] text-zinc-600">
				{formatRelativeTime(d.startedAt)}
			</div>
		</div>
	{/if}
</div>
