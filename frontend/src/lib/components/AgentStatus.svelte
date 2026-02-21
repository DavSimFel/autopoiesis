<script lang="ts">
	import type { UIEvent, AgentStatusData } from '$lib/types';
	import { formatRelativeTime, statusColor } from '$lib/utils';

	let { event }: { event: UIEvent<AgentStatusData> } = $props();

	const d = $derived(event.data);
	const dotClass = $derived(statusColor(d.status));
	const lastSeenStr = $derived(formatRelativeTime(d.lastSeen));
</script>

<div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 backdrop-blur-sm">
	<!-- Header row -->
	<div class="mb-3 flex items-center gap-3">
		<!-- Health dot with pulse for busy/healthy -->
		<span class="relative flex h-3 w-3 shrink-0">
			{#if d.status === 'healthy' || d.status === 'busy'}
				<span
					class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 {dotClass}"
				></span>
			{/if}
			<span class="relative inline-flex h-3 w-3 rounded-full {dotClass}"></span>
		</span>

		<div class="min-w-0 flex-1">
			<div class="flex items-center gap-2">
				<h3 class="truncate text-sm font-semibold text-zinc-100">{d.name}</h3>
				<span class="text-xs capitalize text-zinc-500">{d.status}</span>
			</div>
			<p class="text-xs text-zinc-500">ID: {d.agentId}</p>
		</div>

		{#if d.uptime}
			<span class="text-xs text-zinc-500">↑ {d.uptime}</span>
		{/if}
	</div>

	<!-- Counts row -->
	<div class="grid grid-cols-3 gap-2">
		<div class="rounded-lg bg-zinc-800/50 p-2 text-center">
			<div class="text-lg font-bold leading-none text-zinc-100">{d.pendingApprovals}</div>
			<div class="mt-0.5 text-[10px] text-zinc-500">Approvals</div>
		</div>
		<div class="rounded-lg bg-zinc-800/50 p-2 text-center">
			<div class="text-lg font-bold leading-none text-zinc-100">{d.activeTasks}</div>
			<div class="mt-0.5 text-[10px] text-zinc-500">Active</div>
		</div>
		<div class="rounded-lg bg-zinc-800/50 p-2 text-center">
			<div class="text-lg font-bold leading-none text-zinc-100">{d.queueDepth}</div>
			<div class="mt-0.5 text-[10px] text-zinc-500">Queued</div>
		</div>
	</div>

	<!-- Footer -->
	<div class="mt-3 text-right text-[10px] text-zinc-600">
		Last seen {lastSeenStr}
	</div>
</div>
