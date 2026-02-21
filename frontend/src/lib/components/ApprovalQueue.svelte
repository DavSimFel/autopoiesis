<script lang="ts">
	import type { UIEvent, ApprovalQueueData } from '$lib/types';
	import ApprovalItem from './ApprovalItem.svelte';

	let {
		event,
		onresolve,
	}: {
		event: UIEvent<ApprovalQueueData>;
		onresolve?: (id: string) => void;
	} = $props();

	const d = $derived(event.data);
</script>

<div class="space-y-3">
	<!-- Queue header -->
	<div class="flex items-center justify-between px-1">
		<h2 class="text-sm font-semibold text-zinc-300">
			Pending Approvals
		</h2>
		<span class="rounded-full bg-amber-900/30 px-2 py-0.5 text-xs font-semibold text-amber-400 border border-amber-800/40">
			{d.totalPending}
		</span>
	</div>

	<!-- Individual items — each gets its own synthetic UIEvent wrapper -->
	{#each d.items as item (item.approvalId)}
		<ApprovalItem
			event={{
				type: 'approval-item',
				data: item,
				meta: {
					...event.meta,
					id: `${event.meta.id}:${item.approvalId}`,
					resolvable: true,
					ephemeral: false,
				},
			}}
			{onresolve}
		/>
	{:else}
		<div class="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 text-center text-sm text-zinc-500">
			No pending approvals ✓
		</div>
	{/each}
</div>
