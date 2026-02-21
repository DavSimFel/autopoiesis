<script lang="ts">
	import type { SSEStatus } from '$lib/mcp-client';

	let {
		status,
	}: {
		status: SSEStatus;
	} = $props();

	const config: Record<SSEStatus, { color: string; label: string; pulse: boolean }> = {
		connecting: { color: 'bg-amber-500', label: 'Connecting…', pulse: true },
		connected: { color: 'bg-emerald-500', label: 'Live', pulse: false },
		reconnecting: { color: 'bg-orange-500', label: 'Reconnecting…', pulse: true },
		closed: { color: 'bg-zinc-500', label: 'Offline', pulse: false },
	};

	const cfg = $derived(config[status]);
</script>

<div class="flex items-center gap-1.5">
	<span class="relative flex h-2 w-2">
		{#if cfg.pulse}
			<span class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 {cfg.color}"></span>
		{/if}
		<span class="relative inline-flex h-2 w-2 rounded-full {cfg.color}"></span>
	</span>
	<span class="text-[10px] text-zinc-500">{cfg.label}</span>
</div>
